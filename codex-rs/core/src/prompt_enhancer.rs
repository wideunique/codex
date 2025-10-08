use crate::config::PromptEnhancerConfig;
use codex_protocol::protocol::EnhancePromptRequest;
use codex_protocol::protocol::PromptEnhancementError;
use codex_protocol::protocol::PromptEnhancementErrorCode;
use reqwest::StatusCode;
use tokio_util::sync::CancellationToken;
use tracing::debug;
use tracing::warn;

#[async_trait::async_trait]
pub trait PromptEnhancerClient: Send + Sync {
    async fn enhance(
        &self,
        request: EnhancePromptRequest,
        cancel: CancellationToken,
    ) -> Result<String, PromptEnhancementError>;
}

pub struct HttpPromptEnhancerClient {
    config: PromptEnhancerConfig,
    client: reqwest::Client,
}

impl HttpPromptEnhancerClient {
    pub fn new(config: PromptEnhancerConfig) -> Self {
        let timeout = config.timeout;
        let client = reqwest::Client::builder()
            .timeout(timeout)
            .build()
            .unwrap_or_else(|err| {
                warn!("failed to build prompt enhancer client with timeout: {err:#}");
                reqwest::Client::new()
            });
        Self { config, client }
    }

    fn map_error_code(code: &str) -> PromptEnhancementErrorCode {
        match code.to_ascii_lowercase().as_str() {
            "unsupported_format" => PromptEnhancementErrorCode::UnsupportedFormat,
            "draft_too_large" | "payload_too_large" => PromptEnhancementErrorCode::DraftTooLarge,
            "timeout" => PromptEnhancementErrorCode::Timeout,
            "service_unavailable" | "overloaded" => PromptEnhancementErrorCode::ServiceUnavailable,
            _ => PromptEnhancementErrorCode::Internal,
        }
    }

    fn map_status(status: StatusCode) -> PromptEnhancementErrorCode {
        if status == StatusCode::REQUEST_TIMEOUT
            || status == StatusCode::GATEWAY_TIMEOUT
            || status == StatusCode::TOO_MANY_REQUESTS
        {
            return PromptEnhancementErrorCode::Timeout;
        }
        if status == StatusCode::PAYLOAD_TOO_LARGE {
            return PromptEnhancementErrorCode::DraftTooLarge;
        }
        if status == StatusCode::UNSUPPORTED_MEDIA_TYPE {
            return PromptEnhancementErrorCode::UnsupportedFormat;
        }
        if status.is_client_error() || status.is_server_error() {
            PromptEnhancementErrorCode::ServiceUnavailable
        } else {
            PromptEnhancementErrorCode::Internal
        }
    }

    fn cancelled_error() -> PromptEnhancementError {
        PromptEnhancementError {
            code: PromptEnhancementErrorCode::Internal,
            message: "cancelled".to_string(),
        }
    }

    fn request_error(
        message: impl Into<String>,
        code: PromptEnhancementErrorCode,
    ) -> PromptEnhancementError {
        PromptEnhancementError {
            code,
            message: message.into(),
        }
    }
}

#[derive(Debug, serde::Deserialize)]
struct PromptEnhancerHttpResponse {
    enhanced_prompt: Option<String>,
    error: Option<PromptEnhancerHttpError>,
}

#[derive(Debug, serde::Deserialize)]
struct PromptEnhancerHttpError {
    code: Option<String>,
    message: Option<String>,
}

#[async_trait::async_trait]
impl PromptEnhancerClient for HttpPromptEnhancerClient {
    async fn enhance(
        &self,
        request: EnhancePromptRequest,
        cancel: CancellationToken,
    ) -> Result<String, PromptEnhancementError> {
        if cancel.is_cancelled() {
            return Err(Self::cancelled_error());
        }

        let endpoint = match &self.config.endpoint {
            Some(endpoint) => endpoint,
            None => {
                return Err(Self::request_error(
                    "Prompt enhancer endpoint is not configured.",
                    PromptEnhancementErrorCode::ServiceUnavailable,
                ));
            }
        };

        debug!("sending prompt enhancement request to {endpoint}");
        let request_future = self.client.post(endpoint).json(&request).send();

        tokio::pin!(request_future);
        tokio::select! {
            _ = cancel.cancelled() => {
                return Err(Self::cancelled_error());
            }
            response = &mut request_future => {
                let response = response.map_err(|err| {
                    warn!("prompt enhancer request failed: {err:#}");
                    if err.is_timeout() {
                        PromptEnhancementError {
                            code: PromptEnhancementErrorCode::Timeout,
                            message: err.to_string(),
                        }
                    } else if err.is_connect() {
                        PromptEnhancementError {
                            code: PromptEnhancementErrorCode::ServiceUnavailable,
                            message: err.to_string(),
                        }
                    } else {
                        PromptEnhancementError {
                            code: PromptEnhancementErrorCode::Internal,
                            message: err.to_string(),
                        }
                    }
                })?;

                if cancel.is_cancelled() {
                    return Err(Self::cancelled_error());
                }

                let status = response.status();
                debug!("received response with status: {status}");

                let body_future = response.text();
                tokio::pin!(body_future);
                let body = tokio::select! {
                    _ = cancel.cancelled() => {
                        return Err(Self::cancelled_error());
                    }
                    body = &mut body_future => body,
                };

                let body = body.map_err(|err| {
                    warn!("failed to read response body: {err:#}");
                    PromptEnhancementError {
                        code: if err.is_timeout() {
                            PromptEnhancementErrorCode::Timeout
                        } else {
                            PromptEnhancementErrorCode::Internal
                        },
                        message: err.to_string(),
                    }
                })?;

                debug!("response body (first 500 chars): {}", &body.chars().take(500).collect::<String>());

                if cancel.is_cancelled() {
                    return Err(Self::cancelled_error());
                }

                if status.is_success() {
                    let parsed: PromptEnhancerHttpResponse = serde_json::from_str(&body).map_err(|err| {
                        warn!("failed to parse success response as JSON: {err:#}");
                        warn!("response body was: {body}");
                        PromptEnhancementError {
                            code: PromptEnhancementErrorCode::Internal,
                            message: format!("Failed to parse enhancer response: {err}"),
                        }
                    })?;

                    if let Some(prompt) = parsed.enhanced_prompt {
                        debug!("successfully received enhanced prompt ({} chars)", prompt.len());
                        return Ok(prompt);
                    }

                    if let Some(error) = parsed.error {
                        let code = error
                            .code
                            .as_deref()
                            .map(Self::map_error_code)
                            .unwrap_or(PromptEnhancementErrorCode::Internal);
                        let message = error
                            .message
                            .unwrap_or_else(|| {
                                "Prompt enhancer returned an error without message".to_string()
                            });
                        warn!("prompt enhancer returned error in success response: {message}");
                        return Err(Self::request_error(message, code));
                    }

                    warn!("prompt enhancer returned empty success response");
                    return Err(Self::request_error(
                        "Prompt enhancer returned an empty response.",
                        PromptEnhancementErrorCode::Internal,
                    ));
                }

                let parsed: Option<PromptEnhancerHttpResponse> = serde_json::from_str(&body).ok();
                if let Some(parsed) = parsed
                    && let Some(error) = parsed.error
                {
                    let code = error
                        .code
                        .as_deref()
                        .map(Self::map_error_code)
                        .unwrap_or_else(|| Self::map_status(status));
                    let message = error
                        .message
                        .unwrap_or_else(|| format!("Prompt enhancer error ({status}): {body}"));
                    return Err(Self::request_error(message, code));
                }

                let code = Self::map_status(status);
                Err(Self::request_error(
                    format!("Prompt enhancer HTTP {status}: {body}"),
                    code,
                ))
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_protocol::protocol::PromptEnhancerFormat;
    use codex_protocol::protocol::WorkspaceContext;
    use serde_json::json;
    use tokio_util::sync::CancellationToken;
    use wiremock::Mock;
    use wiremock::MockServer;
    use wiremock::ResponseTemplate;
    use wiremock::matchers::method;
    use wiremock::matchers::path;

    #[tokio::test]
    async fn enhance_success() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/enhance"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "enhanced_prompt": "better prompt"
            })))
            .expect(1)
            .mount(&server)
            .await;

        let config = PromptEnhancerConfig {
            endpoint: Some(format!("{}/enhance", server.uri())),
            formats: vec![PromptEnhancerFormat::Text],
            locale: None,
            timeout: std::time::Duration::from_secs(1),
            max_request_bytes: None,
            supports_async_cancel: true,
            max_recent_messages: 4,
        };
        let client = HttpPromptEnhancerClient::new(config);

        let request = EnhancePromptRequest {
            request_id: "req".to_string(),
            format: PromptEnhancerFormat::Text,
            locale: None,
            draft: "draft".to_string(),
            cursor_byte_offset: Some(0),
            workspace_context: WorkspaceContext {
                model: "model".to_string(),
                reasoning_effort: None,
                cwd: std::env::current_dir().unwrap(),
                recent_messages: Vec::new(),
            },
        };

        let result = client
            .enhance(request, CancellationToken::new())
            .await
            .expect("success");
        assert_eq!(result, "better prompt");
    }

    #[tokio::test]
    async fn enhance_maps_error_code() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/enhance"))
            .respond_with(ResponseTemplate::new(400).set_body_json(json!({
                "error": {
                    "code": "draft_too_large",
                    "message": "too big"
                }
            })))
            .expect(1)
            .mount(&server)
            .await;

        let config = PromptEnhancerConfig {
            endpoint: Some(format!("{}/enhance", server.uri())),
            formats: vec![PromptEnhancerFormat::Text],
            locale: None,
            timeout: std::time::Duration::from_secs(1),
            max_request_bytes: None,
            supports_async_cancel: true,
            max_recent_messages: 4,
        };
        let client = HttpPromptEnhancerClient::new(config);
        let request = EnhancePromptRequest {
            request_id: "req".to_string(),
            format: PromptEnhancerFormat::Text,
            locale: None,
            draft: "draft".to_string(),
            cursor_byte_offset: Some(0),
            workspace_context: WorkspaceContext {
                model: "model".to_string(),
                reasoning_effort: None,
                cwd: std::env::current_dir().unwrap(),
                recent_messages: Vec::new(),
            },
        };

        let err = client
            .enhance(request, CancellationToken::new())
            .await
            .expect_err("should fail");
        assert_eq!(err.code, PromptEnhancementErrorCode::DraftTooLarge);
        assert_eq!(err.message, "too big");
    }

    #[tokio::test]
    async fn enhance_handles_timeout_status() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/enhance"))
            .respond_with(ResponseTemplate::new(504))
            .expect(1)
            .mount(&server)
            .await;

        let config = PromptEnhancerConfig {
            endpoint: Some(format!("{}/enhance", server.uri())),
            formats: vec![PromptEnhancerFormat::Text],
            locale: None,
            timeout: std::time::Duration::from_secs(1),
            max_request_bytes: None,
            supports_async_cancel: true,
            max_recent_messages: 4,
        };
        let client = HttpPromptEnhancerClient::new(config);
        let request = EnhancePromptRequest {
            request_id: "req".to_string(),
            format: PromptEnhancerFormat::Text,
            locale: None,
            draft: "draft".to_string(),
            cursor_byte_offset: Some(0),
            workspace_context: WorkspaceContext {
                model: "model".to_string(),
                reasoning_effort: None,
                cwd: std::env::current_dir().unwrap(),
                recent_messages: Vec::new(),
            },
        };

        let err = client
            .enhance(request, CancellationToken::new())
            .await
            .expect_err("timeout");
        assert_eq!(err.code, PromptEnhancementErrorCode::Timeout);
    }

    #[tokio::test]
    async fn enhance_respects_cancellation() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/enhance"))
            .respond_with(
                ResponseTemplate::new(200)
                    .set_delay(std::time::Duration::from_millis(200))
                    .set_body_json(json!({ "enhanced_prompt": "ok" })),
            )
            .mount(&server)
            .await;

        let config = PromptEnhancerConfig {
            endpoint: Some(format!("{}/enhance", server.uri())),
            formats: vec![PromptEnhancerFormat::Text],
            locale: None,
            timeout: std::time::Duration::from_secs(5),
            max_request_bytes: None,
            supports_async_cancel: true,
            max_recent_messages: 4,
        };
        let client = HttpPromptEnhancerClient::new(config);
        let request = EnhancePromptRequest {
            request_id: "req".to_string(),
            format: PromptEnhancerFormat::Text,
            locale: None,
            draft: "draft".to_string(),
            cursor_byte_offset: Some(0),
            workspace_context: WorkspaceContext {
                model: "model".to_string(),
                reasoning_effort: None,
                cwd: std::env::current_dir().unwrap(),
                recent_messages: Vec::new(),
            },
        };

        let cancel = CancellationToken::new();
        let cancel_clone = cancel.clone();
        tokio::spawn(async move {
            tokio::time::sleep(std::time::Duration::from_millis(50)).await;
            cancel_clone.cancel();
        });

        let err = client
            .enhance(request, cancel)
            .await
            .expect_err("cancelled");
        assert_eq!(err.code, PromptEnhancementErrorCode::Internal);
        assert_eq!(err.message, "cancelled");
    }

    #[tokio::test]
    async fn missing_endpoint_returns_error() {
        let config = PromptEnhancerConfig {
            endpoint: None,
            formats: vec![PromptEnhancerFormat::Text],
            locale: None,
            timeout: std::time::Duration::from_secs(1),
            max_request_bytes: None,
            supports_async_cancel: true,
            max_recent_messages: 4,
        };
        let client = HttpPromptEnhancerClient::new(config);
        let request = EnhancePromptRequest {
            request_id: "req".to_string(),
            format: PromptEnhancerFormat::Text,
            locale: None,
            draft: "draft".to_string(),
            cursor_byte_offset: Some(0),
            workspace_context: WorkspaceContext {
                model: "model".to_string(),
                reasoning_effort: None,
                cwd: std::env::current_dir().unwrap(),
                recent_messages: Vec::new(),
            },
        };

        let err = client
            .enhance(request, CancellationToken::new())
            .await
            .expect_err("missing endpoint");
        assert_eq!(err.code, PromptEnhancementErrorCode::ServiceUnavailable);
    }
}
