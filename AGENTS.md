# Repository Guidelines

## Service Name

- `TR GPT` ：台灣林內資訊課所開發的 AI 機器人，與目前市面上的商業大語言 LLM 模型串接，可以讓用戶詢問任何問題。以後會整合公司內相關服務，
- 提供企業化 AI Agent。

## Project Structure & Module Organization

- `app.py`: Main Quart/Bot Framework app (Teams bot, routes, schedulers).
- `graph_api.py`, `token_manager.py`: Microsoft Graph helpers and auth.
- `s3_manager.py`: Audit log persistence to S3 and local cache `local_audit_logs/`.
- `app_test.py`, `test_config.py`: Lightweight runtime checks and env toggling.
- `requirements.txt`, `startup.sh`: Dependencies and Azure App Service start script.
- `.github/workflows/`: CI build and Azure Web App deploy.
- Keep new modules in root; prefer small, single‑purpose files.

## Build, Test, and Development Commands

- Create venv: `python -m venv venv && source venv/bin/activate` (Windows: `venv\Scripts\activate`).
- Install deps: `pip install -r requirements.txt`.
- Run locally (ASGI): `hypercorn app:app --bind 0.0.0.0:8000`.
- Quick health check: `curl http://localhost:8000/ping` (see `app_test.py`).
- Env switch demo: `python test_config.py`.
- Azure start (container): `bash startup.sh`.

## Coding Style & Naming Conventions

- Python, PEP 8: 4‑space indent, max line length ~120, type hints where practical.
- Names: modules/files `snake_case.py`; functions/vars `snake_case`; classes `CamelCase`.
- Logging: use `logging` (already configured) instead of prints for new code.
- Config: read via `os.getenv` and `.env` (dotenv loaded in `app.py`). Never commit secrets.

## Testing Guidelines

- Framework: lightweight functional checks exist (`app_test.py`). If adding tests, prefer `pytest` style and keep fast.
- Test names: `test_<module>.py`, functions `test_<behavior>()`.
- Manual checks: `/ping`, `/api/test` endpoints; validate Teams flows and S3 uploads in logs.

## Commit & Pull Request Guidelines

- Commits: concise, present‑tense summary; include scope (e.g., "todo: fix reminder card"). English or zh‑TW acceptable. Group related changes.
- PRs: clear description, motivation, and screenshots for UI/cards; list key env vars touched; link issues; note breaking changes and rollout steps.
- CI: ensure `requirements.txt` is updated; verify local run before PR.

## Security & Configuration Tips

- Required env (examples): `BOT_APP_ID`, `BOT_APP_PASSWORD`, `TENANT_ID`, `CLIENT_ID`, `CLIENT_SECRET`, `USE_AZURE_OPENAI`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_KEY`, S3 creds for `s3_manager`.
- Store secrets in `.env` locally and GitHub/Azure secrets in CI/CD. Do not log sensitive values.
