# AI Meeting Proxy

FastAPI PoC for an AI meeting proxy with avatar bot capabilities:
- Speech-to-Text transcription (GCP Speech-to-Text)
- Dialogue generation/summarization (Vertex AI Gemini)
- AI Avatar Bot that joins Google Meet and participates in conversations via Recall.ai
- Text-to-Speech voice responses (GCP Cloud TTS)
- Web admin dashboard for configuration and bot control

## Project Structure

```
.
├── main.py                  # FastAPI app, original endpoints, startup
├── config.py                # Pydantic settings (.env)
├── bot/
│   ├── router.py            # Bot control endpoints (/bot/*)
│   ├── admin_router.py      # Admin API endpoints (/admin/*)
│   ├── tts.py               # Cloud TTS wrapper (Japanese)
│   ├── knowledge.py         # File-based knowledge retrieval
│   ├── persona.py           # Persona profile & system prompt
│   ├── conversation.py      # Conversation session management
│   └── recall_client.py     # Recall.ai API client
├── knowledge/
│   ├── profile.md           # Bot persona profile
│   └── docs/                # Knowledge base documents
│       └── sample.md
├── static/
│   └── index.html           # Web admin dashboard
├── tests/
│   ├── test_api_guards.py   # Auth & security boundary tests
│   ├── test_bot.py          # Bot endpoint tests
│   ├── test_admin.py        # Admin endpoint tests
│   ├── test_tts.py          # TTS tests
│   ├── test_knowledge.py    # Knowledge base tests
│   ├── test_persona.py      # Persona tests
│   └── test_conversation.py # Conversation tests
├── docker/
│   └── Dockerfile           # Cloud Run image
├── requirements.txt
├── requirements-dev.txt
└── .env.example
```

## Endpoints

### Core API

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/health` | No | Liveness probe |
| GET | `/health/ready` | No | Dependency readiness check |
| GET | `/metrics` | Yes | Request metrics |
| POST | `/transcribe` | Yes | Audio file -> transcription |
| POST | `/chat` | Yes | Text -> Gemini response (optional SSE) |
| POST | `/meeting-proxy` | Yes | Audio -> transcript -> Gemini (optional SSE) |
| POST | `/streaming/transcribe` | Yes | Placeholder for streaming |

### Bot Control (`/bot`)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/bot/join` | Yes | Send bot to join a Google Meet |
| GET | `/bot/{bot_id}/status` | Yes | Get bot status |
| POST | `/bot/{bot_id}/leave` | Yes | Remove bot from meeting |
| POST | `/bot/webhook/transcript` | No | Receive real-time transcript from Recall.ai |

### Admin Management (`/admin`)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/admin/status` | Yes | System status overview |
| GET | `/admin/profile` | Yes | Get persona profile |
| PUT | `/admin/profile` | Yes | Update persona profile |
| GET | `/admin/settings` | Yes | Get TTS/bot settings |
| PUT | `/admin/settings` | Yes | Update TTS/bot settings |
| POST | `/admin/tts/preview` | Yes | Synthesize voice preview |
| GET | `/admin/knowledge` | Yes | List knowledge documents |
| GET | `/admin/knowledge/{filename}` | Yes | Get document content |
| PUT | `/admin/knowledge/{filename}` | Yes | Create/update document |
| DELETE | `/admin/knowledge/{filename}` | Yes | Delete document |

### Web UI

- Admin dashboard: `http://localhost:8000/static/index.html` (or `/`)
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Prerequisites

1. Python 3.11+
2. GCP project with APIs enabled:
   - Speech-to-Text API
   - Vertex AI API
   - Cloud Text-to-Speech API
3. GCP credentials with roles:
   - `roles/speech.client`
   - `roles/aiplatform.user`
   - `roles/texttospeech.client` (for TTS)
4. (Optional) [Recall.ai](https://recall.ai) API key for Google Meet bot integration

## Setup

1. Copy env template and edit values.

```bash
cp .env.example .env
```

2. Install dependencies.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. Authenticate with GCP.

```bash
gcloud auth application-default login
```

4. Run the API.

```bash
uvicorn main:app --reload
```

## Configuration

Core settings in `.env`:

```bash
# GCP
GCP_PROJECT_ID=your-project-id
GCP_LOCATION=us-central1
GEMINI_MODEL=gemini-1.5-pro

# Auth (optional - skipped when unset)
API_KEY=your-api-key

# Avatar Bot
PERSONA_PROFILE_PATH=knowledge/profile.md
KNOWLEDGE_DIR=knowledge/docs
TTS_VOICE_NAME=ja-JP-Neural2-B
TTS_SPEAKING_RATE=1.0
BOT_DISPLAY_NAME=AI Avatar
RESPONSE_TRIGGERS=
MAX_CONVERSATION_HISTORY=20

# Recall.ai (optional - required for Meet bot)
RECALL_API_KEY=your-recall-api-key
WEBHOOK_BASE_URL=https://your-deployment-url
```

## Architecture

### Avatar Bot Conversation Flow

```
Google Meet
  └─> Recall.ai Bot (listens to meeting audio)
        └─> Webhook: real-time transcript
              └─> /bot/webhook/transcript
                    ├─ Keyword search in knowledge base
                    ├─ Build system prompt (persona + knowledge context)
                    ├─ Conversation history management
                    ├─ Gemini generates response
                    ├─ Cloud TTS synthesizes audio (Japanese)
                    └─> Recall.ai sends audio back to meeting
```

### Response Triggers

The bot responds when:
- Bot name is mentioned in the utterance
- A direct question is detected (`？`, `?`, `か`, `か。`)
- Custom trigger keywords match (configured via `RESPONSE_TRIGGERS`)

## Security Controls

- Optional API key auth with `X-API-Key` header
- Audio type validation (MIME + extension + magic bytes)
- Upload size limit (`MAX_AUDIO_SIZE_BYTES`, default 10 MB)
- Text input size limit (`MAX_INPUT_CHARS`, default 20,000)
- Request ID on every response (`X-Request-ID`)
- Generic error responses (no stack traces leaked)
- Knowledge filename validation (path traversal protection)

## Tests

```bash
pip install -r requirements-dev.txt
GCP_PROJECT_ID=local-test pytest -q
```

## Cloud Run Deployment

```bash
gcloud run deploy ai-meeting-proxy-poc \
  --source . \
  --region us-central1 \
  --allow-unauthenticated
```

Or build with Docker:

```bash
docker build -f docker/Dockerfile -t ai-meeting-proxy-poc:latest .
```

## CI/CD

- GitHub Actions workflow: `.github/workflows/ci.yml`
- Runs lint, security scan, and unit tests on push/PR

## Tech Stack

Python 3.11 | FastAPI | Pydantic | GCP Speech-to-Text | Vertex AI (Gemini) | Cloud Text-to-Speech | Recall.ai | Docker | ruff | bandit
