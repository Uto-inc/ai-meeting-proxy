# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI Meeting Proxy is a FastAPI application for AI-powered meeting participation. Google Calendar連携でAI自動参加、資料ベースの質問応答（回答/持ち帰り分類）、Gemini議事録生成、Google Docsエクスポートを提供。SQLiteでデータ永続化、Recall.ai経由でGoogle Meetに参加。

## Commands

```bash
# Install
pip install -r requirements.txt

# Dev dependencies (includes ruff, bandit, pytest)
pip install -r requirements-dev.txt

# Dev server (auto-reload)
uvicorn main:app --reload

# Run tests (84 tests)
GCP_PROJECT_ID=local-test pytest -q

# Lint & format
ruff check main.py config.py tests/
ruff format main.py config.py tests/

# Security scan
bandit -r main.py config.py -q

# Docker build
docker build -f docker/Dockerfile -t ai-meeting-proxy-poc:latest .
```

## Slash Commands

| Command | Purpose |
|---------|---------|
| `/verify` | Full verification loop (lint, security, tests, diff review) before committing |
| `/code-review` | Quality and security review of current changes |
| `/tdd` | Test-driven development workflow (RED -> GREEN -> REFACTOR) |

## Critical Rules

### Python Conventions
- Python 3.9+ compatible — use `from __future__ import annotations` in all modules
- Type hints on all function signatures
- `logging.getLogger()` instead of `print()` — hooks will flag print() in modified files
- f-strings for formatting, never `%` or `.format()`
- Max line length: 120 characters (enforced by ruff)
- Imports sorted by ruff (stdlib, third-party, local)
- Functions under 50 lines, files under 800 lines — hooks warn above 800

### FastAPI Patterns
- All non-health endpoints must use `Depends(_auth_guard)`
- Blocking GCP calls must be wrapped in `run_in_threadpool()`
- HTTP errors use proper status codes: 400 (bad input), 401 (auth), 413 (size), 503 (service unavailable)
- Error responses must not leak stack traces or internal details

### Security Checklist (before every commit)
- No hardcoded secrets, API keys, or tokens
- All user inputs validated (Pydantic or `_normalize_text_input`)
- File uploads triple-validated (MIME + extension + magic bytes)
- Run `/verify` to confirm lint + security scan + tests pass

### Git Workflow
- Conventional commit prefixes: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`
- Run `/verify` before committing
- Keep commits focused — one logical change per commit

## Architecture

**Multi-module API** with `main.py` as the entrypoint. Uses async lifespan for DB/scheduler initialization.

### Modules

| Module | Purpose |
|--------|---------|
| `db/` | SQLite schema + async CRUD repository (5 tables: oauth_tokens, meetings, materials, conversation_log, minutes) |
| `auth/` | Google OAuth2 flow (login, callback, status, revoke) |
| `calendar_sync/` | Google Calendar API + 60s auto-join scheduler |
| `materials/` | File upload, Google Drive linking, text extraction (PDF/MD/TXT) |
| `minutes/` | Gemini minutes generation + Google Docs export |
| `bot/` | Recall.ai bot control, meeting conversation with material-aware response classification |

### Key components in `main.py`

- **Lifespan**: async context manager initializes DB, GCP services, TTS, avatar, scheduler; cleans up on shutdown
- **App state**: `repo` (Repository), `speech_client`, `vertex_model` stored on `app.state`
- **Auth**: `_auth_guard` dependency — optional HMAC API key via `X-API-Key` header
- **Routers**: auth, bot, admin, calendar, materials, minutes — all registered in main

### Config (`config.py`)

Pydantic `BaseSettings` subclass loading from `.env`. Key settings: `GCP_PROJECT_ID`, `GCP_LOCATION`, `GEMINI_MODEL`, `API_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `DB_PATH`, `MATERIALS_UPLOAD_DIR`.

## Testing

84 tests across 12 test files covering: API guards, bot endpoints, database CRUD, calendar sync, text extraction, conversation classification, minutes generation, admin, TTS, knowledge, persona, conversation.

### Testing Conventions
- Test files: `tests/test_<module>.py`
- Test functions: `def test_<behavior>() -> None:`
- Use `_set_default_test_settings()` to reset shared state before each test
- Mock GCP services via settings mutation — no real API calls in tests
- DB tests use `tempfile.TemporaryDirectory()` with `aiosqlite`

## Tech Stack

Python 3.9+ | FastAPI | Pydantic | GCP Speech-to-Text | Vertex AI (Gemini) | Cloud TTS | Google Calendar/Drive/Docs API | Recall.ai | SQLite (aiosqlite) | PyPDF2 | Docker | ruff | bandit
