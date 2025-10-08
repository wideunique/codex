# Prompt Enhancer Service (Python)

FastAPI-based service that accepts raw prompts and returns enhanced prompts. The service now provides two enhancement backends:

- **Command mode** – wraps the original `enhance_prompt.sh` shell script.
- **Selenium mode** – drives the Gemini web UI through Selenium to obtain an enhanced prompt.

## Directory Layout

```
.
├── AGENTS.md
├── README.md
├── requirements.txt
├── configs/
│   ├── config.example.yaml
│   └── config.yaml
├── src/
│   ├── __init__.py
│   ├── app.py
│   ├── auth.py
│   ├── config.py
│   ├── enhancer.py
│   ├── main.py
│   ├── models.py
│   ├── mode_command.py
│   └── mode_selenium.py
├── templates/
│   ├── default.txt
│   └── default_cn.txt
└── tests/
    ├── conftest.py
    └── test_server.py
```

**Key changes from the legacy layout**
- Modules that used to live under `src/prompt_enhancer_service/` now sit flat inside `src/`; import them as `from src import ...`.
- The pytest suite moved out of `src/tests/` into top-level `tests/`.
- Entry points run with `python -m src.main` (the old `python -m prompt_enhancer_service.main` path no longer exists).
- Configuration and template directories (`configs/`, `templates/`) are unchanged, but paths in config values should reflect the new module layout when referenced.

## Configuration Surface

| Config item                    | Description                                                         | Default                                |
|--------------------------------|---------------------------------------------------------------------|----------------------------------------|
| `SERVER_ADDRESS`               | HTTP listen address                                                  | `:8080`                                |
| `READ_TIMEOUT`                 | HTTP read timeout (Go duration string syntax)                       | `5s`                                   |
| `WRITE_TIMEOUT`                | HTTP write timeout                                                   | `10s`                                  |
| `API_KEY`                      | Shared secret required for every request                            | _none_ (must be provided)              |
| `ENHANCE_SCRIPT_PATH`          | Path to `enhance_prompt.sh` (command mode)                          | `enhance_prompt.sh`                    |
| `AUTO_CLEANUP_TEMP_FILES`      | Remove temp files after successful command-mode run                 | `false`                                |
| `ENHANCER_MODE`                | Enhancement backend: `selenium` (default) or `command`              | `selenium`                             |
| `SELENIUM_FIREFOX_BINARY`      | Firefox executable path                                             | `/Applications/Firefox.app/Contents/MacOS/firefox` |
| `SELENIUM_FIREFOX_PROFILE_DIR` | Firefox profile directory (blank to auto-detect)                    | _auto-detect_                          |
| `SELENIUM_TIMEOUT`             | Selenium response timeout in seconds                                | `120`                                  |
| `SELENIUM_AUTO_UPDATE_DRIVER`  | Allow `webdriver-manager` to download/update geckodriver            | `false`                                |
| `SELENIUM_SHOW_GUI`            | Launch Firefox with a GUI instead of headless mode                  | `false`                                |
| `ENHANCER_TEMPLATE_PATH`       | Jinja2 template rendered before invoking either mode                | `templates/default.txt`  |

`configs/config.example.yaml` demonstrates a production-friendly configuration with extended timeouts.

## Getting Started

```bash
# from repo root
cd prompt-enhancer-service
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

# Run tests
pytest -q

# Start the service (uses config defaults)
export API_KEY=my-secret
python -m src.main

# Start with an explicit config file
python -m src.main --config configs/config.example.yaml
```

The service listens on `SERVER_ADDRESS` and shuts down cleanly on `SIGINT`/`SIGTERM`. `READ_TIMEOUT`/`WRITE_TIMEOUT` are parsed but only loosely mapped to uvicorn's `timeout_keep_alive`.

### Selenium Mode

- Requires Firefox and a compatible geckodriver. Enable `SELENIUM_AUTO_UPDATE_DRIVER=true` to fetch the driver via `webdriver-manager` (requires internet access).
- Selenium mode is enabled by default. To fall back to the shell script, set `ENHANCER_MODE=command` or send `"mode": "command"` in the request body.
- Provide `SELENIUM_FIREFOX_PROFILE_DIR` if auto-detection fails.
- Customize the Gemini query template via `ENHANCER_TEMPLATE_PATH` (Jinja2 format).

## API

- **Endpoint:** `POST /api/v1/enhance`
- **Auth:** `Authorization: Bearer <API_KEY>` header (or `X-API-Key`, or `?api_key=` query parameter)
- **Request Body:**

```json
{
  "prompt": "Write unit tests for this function"
}
```

Optional fields include `draft`, `request_id`, `workspace_context`, and `mode`.

- **Success Response (`200 OK`):**

```json
{
  "enhanced_prompt": "Write unit tests for this function [Enhanced]"
}
```

- **Error Response (`4xx/5xx`):**

```json
{
  "error": "invalid_request",
  "message": "prompt must not be empty"
}
```

### Curl Smoke Test

```bash
API_KEY=my-secret python -m src.main &
SERVER_PID=$!
sleep 1

curl -s -X POST http://127.0.0.1:8080/api/v1/enhance \
  -H "Authorization: Bearer my-secret" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Explain context cancellation in Go"}'

kill $SERVER_PID
```

## Testing

- `tests/test_server.py` covers success (200), unauthorized (401), invalid payload (400), unsupported mode (400), Selenium unavailable (503), and default Selenium mode.
- Add more behavioral tests (for example, failure modes for Selenium) using `fastapi.testclient.TestClient`.

## Deployment

Run the packaged entry point (loads YAML + environment variables):

```bash
ENV=prod API_KEY=... \
exec python -m src.main --config configs/config.example.yaml
```

If you need custom uvicorn/gunicorn process management, load the config manually and pass `create_app(cfg)` (see `main.py`).

## Request Extensions

- The optional `mode` field in the request body selects the backend (`command` or `selenium`). If omitted, the configured `ENHANCER_MODE` is used.

## Roadmap Ideas

- Replace the shell script with a native implementation while keeping the `Service` interface stable.
- Enhance error mapping to propagate richer details to API clients.
- Add observability (structured logs, metrics) once requirements are defined.
