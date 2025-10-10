# Repository Guidelines (Python)

## Project Structure & Module Organization
- Core modules now live flat under `src/`: `app.py` (FastAPI application factory), `auth.py`, `config.py`, `enhancer.py`, `models.py`, `mode_command.py`, `mode_selenium.py`, and the CLI entry point `main.py`.
- The Python package is `src`; invoke entry points with `python -m src.main` instead of the historical `prompt_enhancer_service.*` module path.
- Prompt templates remain in `templates/`, configuration samples in `configs/`, and all tests in the top-level `tests/` package (no more `src/tests`).

## Build, Test, and Development Commands
- Create a virtual environment and install dependencies: `python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt`.
- Run tests with `pytest -q` from the project root; direct imports like `from src.app import create_app` work without tweaking `PYTHONPATH`.
- Start locally: `API_KEY=dev python -m src.main --config configs/config.example.yaml`.
- Smoke test with the `curl` example in the README.

## Coding Style & Naming Conventions
- Follow PEP 8 with type hints. Keep modules cohesive and functions narrowly scoped.
- Use Pydantic models for request/response validation and FastAPI dependency injection for authentication.
- Log messages must be actionable, concise, and contextual for debugging.

## Testing Guidelines
- Test behavior rather than implementation details. Cover authentication (401), validation (400), and success (200) paths at minimum.
- Use `fastapi.testclient.TestClient`. Patch `CommandService` in tests for deterministic responses.

## Commit & Pull Request Guidelines
- Use imperative, scoped commit messages (for example, `enhancer: align stderr mapping`).
- Commits must pass `pytest` and include request/response examples when the API surface changes.
