# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI Meeting Proxy is a FastAPI PoC that chains GCP Speech-to-Text transcription with Vertex AI Gemini analysis. It accepts audio uploads, transcribes them, and generates meeting summaries/action items via an LLM. Streaming responses use Server-Sent Events (SSE).

## Commands

```bash
# Install
pip install -r requirements.txt

# Dev dependencies (includes ruff, bandit, pytest)
pip install -r requirements-dev.txt

# Dev server (auto-reload)
uvicorn main:app --reload

# Run tests
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

**Single-file API** — all endpoints and logic live in `main.py` (~393 lines). Configuration is in `config.py` (pydantic-settings, reads from `.env`).

### Key components in `main.py`

- **Global state**: `speech_client` (GCP Speech-to-Text) and `vertex_model` (Gemini GenerativeModel), initialized in `startup_event()`; gracefully `None` if GCP unavailable
- **Auth**: `_auth_guard` dependency — optional HMAC API key via `X-API-Key` header (skipped when `API_KEY` env is unset)
- **Audio validation**: triple-check of MIME type + extension + magic bytes (`_validate_audio_file`); streaming size-limited reads (`_read_upload_limited`)
- **Text input**: `_normalize_text_input` strips and enforces `MAX_INPUT_CHARS`
- **Middleware**: `request_metrics_middleware` attaches `X-Request-ID` UUID, tracks latency/errors in thread-safe in-memory `metrics` dict
- **SSE streaming**: `_stream_gemini_sse` generator yields `data:` lines with `{"delta": ...}` chunks, ends with `event: done`

### Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness probe (no auth) |
| GET | `/health/ready` | Dependency readiness check (no auth) |
| GET | `/metrics` | In-memory request metrics (auth required) |
| POST | `/transcribe` | Audio file -> transcription text |
| POST | `/chat` | Text message -> Gemini response (optional SSE) |
| POST | `/meeting-proxy` | Audio -> transcription -> Gemini (optional SSE) |
| POST | `/streaming/transcribe` | Placeholder for future WebSocket/gRPC streaming |

### Config (`config.py`)

Pydantic `BaseSettings` subclass loading from `.env`. Key settings: `GCP_PROJECT_ID`, `GCP_LOCATION`, `GEMINI_MODEL`, `STT_LANGUAGE_CODE`, `API_KEY`, `MAX_AUDIO_SIZE_BYTES` (default 10MB), `MAX_INPUT_CHARS` (default 20,000).

## Testing

Tests are in `tests/test_api_guards.py` — 4 unit tests covering security boundaries (auth, file size, magic bytes, input length). Tests use `fastapi.testclient.TestClient` and mutate `settings` directly to avoid GCP calls.

### Testing Conventions
- Test files: `tests/test_<module>.py`
- Test functions: `def test_<behavior>() -> None:`
- Use `_set_default_test_settings()` to reset shared state before each test
- Mock GCP services via settings mutation — no real API calls in tests

## Tech Stack

Python 3.11 | FastAPI | Pydantic | GCP Speech-to-Text | Vertex AI (Gemini) | Docker (Cloud Run target) | ruff (lint/format) | bandit (security scan)
