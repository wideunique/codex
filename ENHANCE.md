# Codex CLI Enhancements Overview

Our fork layers a complete prompt-enhancement workflow on top of the standard Codex CLI. The changes cut across protocol, runtime, user interface, and a companion Python service. This document records every functional addition so we can keep the custom surface area in sync with upstream.

## New Features

- **Prompt Enhancer workflow** – a first-class `Ctrl+P` action in the TUI that snapshots the current draft, ships context to a backend, and replaces the input when an enhanced prompt arrives. The composer blocks edits while the request is in flight and surfaces success, failure, or cancellation messages inline.
- **Graceful cancellation and history** – `Esc` aborts an in-progress enhancement (issuing `CancelEnhancePrompt` when the server advertises async cancel support), `Ctrl+R` restores the original draft after an enhancement, and `Ctrl+U` clears the input while keeping the original snapshot available until another enhancement runs.
- **Capability-driven enablement** – prompt enhancement toggles itself based on a capability flag returned in `SessionConfiguredEvent`. When the flag is missing or disabled in config, the shortcut is inert and the footer explains that enhancement is unavailable.
- **Context-rich requests** – enhancement calls include the active model, reasoning settings, working directory, cursor byte offset, and a rolling window of recent assistant/user/system messages, enabling backends to produce tailored rewrites.
- **Dedicated backend service** – a FastAPI-based prompt-enhancer service with interchangeable backends (shell script or Selenium/Gemini), Jinja2 templating, API-key auth, per-mode logging, and a turnkey launcher script.

## Configuration Guide

### 1. Run the Prompt Enhancer Service
1. `cd prompt-enhancer-service`
2. `./bin/run.sh --config configs/config.yaml`
   - Creates a virtualenv, installs `FastAPI`, `selenium`, and friends, then boots `python -m src.main`.
   - Set `API_KEY` in the environment or the YAML file before launch; requests without the key are rejected.
3. Pick a backend:
   - Default `selenium` mode automates Gemini via Firefox (`SELENIUM_FIREFOX_BINARY`, `SELENIUM_FIREFOX_PROFILE_DIR`, `SELENIUM_TIMEOUT`, optional driver auto-update and GUI toggle).
   - `command` mode shells out to `enhance_prompt.sh`; enable by setting `ENHANCER_MODE=command` or passing `{ "mode": "command" }` in the request body.
4. Optional knobs live in `configs/config.example.yaml` and may also be overridden via environment variables (address, timeouts, template path, temp-file persistence, etc.).

### 2. Wire the CLI to the Service
1. Edit `~/.codex/config.toml` and add:
   ```toml
   [prompt_enhancer]
   enabled = true
   endpoint = "http://127.0.0.1:8080/api/v1/enhance"
   format = "text"            # or "json" / "yaml"
   locale = "en-US"           # optional locale hint forwarded to the service
   timeout_ms = 8000           # request timeout enforced client-side
   max_request_bytes = 16384   # guardrail before submitting a draft
   supports_async_cancel = true
   max_recent_messages = 6     # how much chat history to send as context
   ```
2. Restart the CLI; during `SessionConfiguredEvent` the client advertises the capability built from this block. If the service replies with tighter limits (formats, size, cancel support), the UI reconciles with the negotiated values.
3. Verify the footer shows `Ctrl+P` availability; press `Ctrl+P` on a non-empty draft to trigger enhancement.

### 3. Operate the Workflow
- While enhancing, the footer displays a spinner, elapsed time, the configured timeout, and an `Esc to cancel` hint. If the timeout is exceeded client-side, the UI marks it explicitly.
- Cancellation sends a `CancelEnhancePrompt` op only when both configuration and negotiated capability allow async cancel; otherwise the client rolls back locally.
- Enhancement results drop an info banner (`Prompt enhanced.`). Failures map backend error codes to user-facing messages (unsupported format, payload too large, timeout, service unavailable, internal error).
- Use `Ctrl+R` to resurrect the last snapshot if the rewrite is not desirable; the snapshot sticks around until another enhancement completes or the composer is cleared.

## Implementation Details

## Keyboard Shortcuts

| Action                               | Shortcut |
|--------------------------------------|----------|
| Delete entire line                   | `Ctrl+D` |
| Clear input box content              | `Ctrl+U` |
| Cancel prompt enhance operation      | `Ctrl+R` |

### Protocol Surface (codex-rs/protocol)
- `SessionConfiguredEvent` now carries a `capabilities` struct where `prompt_enhancer` advertises supported formats, async cancel, and `max_request_bytes`.
- New submissions: `Op::EnhancePrompt(EnhancePromptRequest)` and `Op::CancelEnhancePrompt { request_id }`. Requests include the editor draft, cursor byte offset, locale hint, and a `WorkspaceContext` bundle (model, reasoning effort, cwd, recent message transcript).
- New events: `EventMsg::PromptEnhancement(PromptEnhancementEvent)` emits lifecycle statuses (`Started`, `Completed`, `Failed`, `Cancelled`) with typed error codes to preserve backward compatibility while enabling richer UX.

### Core Runtime (codex-rs/core)
- `Config` gains `prompt_enhancer: Option<PromptEnhancerConfig>` parsed from TOML (`enabled`, `endpoint`, `format`, `locale`, `timeout_ms`, `max_request_bytes`, `supports_async_cancel`, `max_recent_messages`).
- `prompt_enhancer.rs` implements `PromptEnhancerClient` with an HTTP transport that supports cancellation tokens, maps HTTP and JSON errors to protocol error codes, and enforces the configured timeout.
- `Codex::submit` recognizes the new ops: it sends a `Started` event immediately, tracks a per-request cancellation token, spins a Tokio task to call the enhancer, and emits `Completed` or `Failed` based on the HTTP result. Missing configuration short-circuits with `ServiceUnavailable`.
- Session state holds a `HashMap<request_id, CancellationToken>` so `CancelEnhancePrompt` can abort in-flight work and generates a `Cancelled` event.

### TUI (codex-rs/tui)
- `ChatComposer` introduces `PromptEnhancerState::{Disabled, Idle, Pending}` with a snapshot of the text area, cursor, pending pastes, and attachments. While pending, the composer rejects edits, hides the cursor, disables paste bursts, and records elapsed time for the footer.
- `ChatWidget` stages recent conversation messages into a `VecDeque`, honoring `max_recent_messages`, and defers streaming deltas until the enhancer snapshot is updated. It guards `Ctrl+P` behind capability checks, enforces `max_request_bytes`, and surfaces success/error notifications.
- Footer rendering adds an “Enhancing prompt…” line with spinner, elapsed/timeout display, and automatic “Timed out!” annotation when the deadline passes. Snapshot hints expose prompt-enhancement shortcuts when history is available.
- Keyboard UX additions: `Ctrl+P` triggers enhancement, `Esc` cancels, `Ctrl+R` reverts the last enhancement snapshot, `Ctrl+U` clears the composer while tagging the history state.
- Snapshot tests (`footer_prompt_enhancing*.snap`, `chatwidget` unit tests) cover the new states, ensuring regressions are caught when the rendering or state machine changes.

### Executor / MCP / Rollout
- Executor output ignores `PromptEnhancement` events so non-TUI entry points do not spam logs while still retaining transcript fidelity elsewhere.
- Rollout persistence filters out the new event type to avoid polluting rollout archives unless needed in the future.

### Prompt Enhancer Service (prompt-enhancer-service)
- Restructured as a FastAPI app (`src/app.py`) with dependency-injected authentication, per-request mode selection, and consistent JSON error payloads that match the Rust client’s error mapping.
- Configuration loader (`src/config.py`) merges defaults, YAML, and environment overrides; validates API key presence; normalizes timeouts; and handles template resolution.
- Enhancement coordination (`src/enhancer.py`) late-binds command vs Selenium services, manages temporary files, strips Gemini separator markers, and exposes reusable helpers for both modes.
- Selenium client (`src/utils/gemini_client.py`) encapsulates Firefox profile cloning, geckodriver setup, DOM interactions, and cleanup, with optional GUI mode and automatic driver updates.
- Command mode (`src/mode_command.py`) wraps the legacy `enhance_prompt.sh` workflow while retaining optional temp-file persistence for debugging.
- Request/response models (`src/models.py`) align with the new protocol fields (draft vs prompt, workspace context, cursor offsets, mode override).
- Tests (`tests/test_server.py`, `tests/test_stub_service.py`) cover happy-path enhancement, auth failure, invalid payloads, unsupported modes, Selenium unavailability, and command mode fallback.

### Documentation
- Design documents under `docs/prompt_enhancer_*.md` capture backend protocol, UI behaviour, and research rationale so the enhancement remains discoverable to contributors.

## Change Verification Checklist

- Diffed against `origin/main` to enumerate every new file and touched module.
- Reviewed protocol, core, TUI, and service layers to ensure configuration and runtime behaviour match the documented flow.
- Confirmed tests and snapshots exist for the new functionality; they should be rerun after any enhancement-related change (`cargo test -p codex-tui`, `pytest prompt-enhancer-service`).
