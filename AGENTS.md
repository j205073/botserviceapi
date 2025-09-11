# Repository Guidelines

## Service Name

- `TR GPT` ：台灣林內資訊課所開發的 AI 機器人，與目前市面上的商業大語言 LLM 模型串接，可以讓用戶詢問任何問題。以後會整合公司內相關服務，
- 提供企業化 AI Agent。

## Project Structure & Module Organization
- Root modules: `app.py` (Quart/Bot Framework entry, routes, schedulers), `graph_api.py`, `token_manager.py`, `s3_manager.py`.
- Layered folders:
  - `application/`, `domain/`, `infrastructure/`, `presentation/`, `core/`, `shared/` — keep files small and single‑purpose.
- Tests and utilities: `app_test.py`, `test_config.py`, `simple_test.py`.
- CI/CD: `.github/workflows/` (build + Azure Web App deploy).
- Assets/cache: `local_audit_logs/` for S3 audit log cache.

## Build, Test, and Development Commands
- Create venv: `python -m venv venv && source venv/bin/activate` (Windows: `venv\\Scripts\\activate`).
- Install deps: `pip install -r requirements.txt`.
- Run locally (ASGI): `hypercorn app:app --bind 0.0.0.0:8000`.
- Health check: `curl http://localhost:8000/ping` (see `app_test.py`).
- Env switch demo: `python test_config.py`.
- Azure container start: `bash startup.sh`.

## Coding Style & Naming Conventions
- Python, PEP 8: 4‑space indent, ~120 char lines; add type hints where practical.
- Names: modules/files `snake_case.py`; functions/vars `snake_case`; classes `CamelCase`.
- Logging: use `logging` (configured in `app.py`); avoid `print` in new code.
- Config: read via `os.getenv`; `.env` is loaded in `app.py`. Never commit secrets.

## Testing Guidelines
- Keep tests fast and isolated; prefer `pytest` style.
- Naming: `tests/test_<module>.py` and functions `test_<behavior>()`.
- Manual checks: `/ping`, `/api/test` endpoints; verify Teams flows and S3 uploads in logs.

## Commit & Pull Request Guidelines
- Commits: concise, present‑tense with scope (e.g., "todo: add smart add dedupe"). English or zh‑TW acceptable.
- PRs: motivation, summary, screenshots for UI/cards, list env vars touched, linked issues, breaking changes + rollout steps.
- CI: update `requirements.txt` when adding deps; verify local run before PR.

## Security & Configuration Tips
- Required env (examples): `BOT_APP_ID`, `BOT_APP_PASSWORD`, `TENANT_ID`, `CLIENT_ID`, `CLIENT_SECRET`, `USE_AZURE_OPENAI`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_KEY`, S3 creds for `s3_manager`.
- Store secrets in `.env` locally and GitHub/Azure secrets in CI/CD. Do not log sensitive values; redact PII in audit logs.
