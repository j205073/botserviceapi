# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TR GPT is a Microsoft Teams bot developed by Taiwan Rinnai's IT department. It integrates with commercial LLM models to provide AI assistance for various corporate functions including todo management, meeting room booking, and general Q&A.

## Build, Test, and Development Commands

### Environment Setup
- Create virtual environment: `python -m venv venv`
- Activate (Linux/Mac): `source venv/bin/activate`  
- Activate (Windows): `venv\Scripts\activate`
- Install dependencies: `pip install -r requirements.txt`

### Running the Application
- Local development (ASGI): `hypercorn app:app --bind 0.0.0.0:8000`
- Health check: `curl http://localhost:8000/ping`
- Environment config test: `python test_config.py`
- Azure deployment start: `bash startup.sh`

### Testing
- Basic functional checks are in `app_test.py` (lightweight testing approach)
- Test endpoints: `/ping` and `/api/test` for manual verification
- Validate Teams bot flows and S3 uploads through application logs

## Architecture & Core Components

### Main Application Structure
- `app.py` - Main Quart/Bot Framework application with Teams bot integration, API routes, and background schedulers
- `graph_api.py` + `token_manager.py` - Microsoft Graph API helpers and OAuth token management
- `s3_manager.py` - Audit log persistence to AWS S3 with local caching in `local_audit_logs/`

### Key Features
- **Dual Memory System**: Working memory (recent conversation context) + audit logs (complete records)
- **Teams Integration**: Bot Framework adapter for Microsoft Teams messaging
- **Todo Management**: Personal task lists with automatic cleanup
- **Meeting Room Booking**: Integration with Microsoft Graph for room reservations
- **AI Intent Analysis**: Automatic intent recognition when enabled via `ENABLE_AI_INTENT_ANALYSIS`
- **Model Switching**: Dynamic AI model selection (when not in Azure-only mode)

### Data Flow
1. Teams messages → Bot Framework → Quart routes
2. Conversation context maintained in working memory
3. All interactions logged to local cache → S3 backup (daily)
4. Microsoft Graph API calls for calendar/room booking features

## Environment Configuration

### Required Environment Variables
- Bot Framework: `BOT_APP_ID`, `BOT_APP_PASSWORD`
- Azure AD: `TENANT_ID`, `CLIENT_ID`, `CLIENT_SECRET`
- OpenAI: `USE_AZURE_OPENAI`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_KEY`
- AWS S3: S3 credentials for audit log persistence
- Feature toggles: `ENABLE_AI_INTENT_ANALYSIS`

### Configuration Management
- Use `.env` file for local development (loaded via python-dotenv)
- Store secrets in GitHub/Azure secrets for CI/CD
- Never commit secrets to repository

## Coding Conventions

### Style Guidelines
- Python PEP 8: 4-space indentation, ~120 character line limit
- Naming: `snake_case` for modules/functions/variables, `CamelCase` for classes
- Use `logging` module instead of print statements for new code
- Type hints where practical

### File Organization
- Keep modules in root directory
- Prefer small, single-purpose files
- Follow existing patterns for new components

## Deployment & CI/CD

- Azure App Service deployment via `.github/workflows/`
- Container startup via `startup.sh` script
- Ensure `requirements.txt` is updated before creating PRs
- Verify local functionality before deployment

## Key Bot Commands

The bot responds to various commands and natural language inputs:
- `@help` - Display function menu
- `@ls` - List todos  
- `@add <content>` - Add todo item
- `@book-room` - Meeting room booking
- `@info` - Personal information
- `@you` - Bot introduction
- `@status` - System status
- `@new-chat` - Clear working memory (preserves audit logs)
- `@model` - Switch AI models (when available)

## Security & Audit

- Comprehensive audit logging to S3 for security and debugging
- Local cache cleared after successful S3 upload
- Working memory vs permanent audit log distinction
- OAuth token management for Microsoft Graph integration