# AI Meeting Proxy

FastAPI-based AI meeting proxy with full meeting lifecycle management:
- **Google Calendar連携**: カレンダーから会議を自動取得、AI自動参加
- **資料管理**: PDF/MD/TXTアップロード、Google Drive連携、テキスト抽出
- **AI Avatar Bot**: Google Meetに参加し、資料ベースで質問応答（Recall.ai経由）
- **回答/持ち帰り分類**: 回答可能な質問は即答、判断が必要な事項は「持ち帰り」として記録
- **議事録生成**: Geminiによる構造化議事録の自動生成、Google Docsエクスポート
- **Web管理画面**: 5タブ構成のダッシュボード（カレンダー、会議履歴、資料管理、設定）

## Project Structure

```
.
├── main.py                        # FastAPI app, lifespan, router registration
├── config.py                      # Pydantic settings (.env)
├── db/
│   ├── schema.py                  # SQLite schema + migrations
│   └── repository.py              # Async CRUD (tokens, meetings, materials, logs, minutes)
├── auth/
│   ├── router.py                  # Google OAuth2 endpoints (/auth/google/*)
│   └── google_oauth.py            # Token management (build, refresh, validate)
├── calendar_sync/
│   ├── router.py                  # Calendar API endpoints (/calendar/*)
│   ├── google_calendar.py         # Google Calendar API wrapper
│   └── scheduler.py               # Background auto-join scheduler (60s interval)
├── materials/
│   ├── router.py                  # Material upload/link endpoints
│   ├── extractor.py               # Text extraction (PDF, MD, TXT)
│   └── drive_client.py            # Google Drive API wrapper
├── minutes/
│   ├── router.py                  # Minutes generation/export endpoints
│   ├── generator.py               # Gemini prompt builder for minutes
│   └── docs_exporter.py           # Google Docs creation/export
├── bot/
│   ├── router.py                  # Bot control endpoints (/bot/*)
│   ├── meeting_conversation.py    # Material-aware conversation + response classification
│   ├── admin_router.py            # Admin API endpoints (/admin/*)
│   ├── tts.py                     # Cloud TTS wrapper (Japanese)
│   ├── knowledge.py               # File-based knowledge retrieval
│   ├── persona.py                 # Persona profile & system prompt
│   ├── conversation.py            # Base conversation session
│   └── recall_client.py           # Recall.ai API client
├── knowledge/
│   ├── profile.md                 # Bot persona profile
│   └── docs/                      # Knowledge base documents
├── static/
│   └── index.html                 # Web admin dashboard (5-tab UI)
├── tests/                         # 84 tests
│   ├── test_api_guards.py         # Auth & security boundary tests
│   ├── test_bot.py                # Bot endpoint tests
│   ├── test_db.py                 # Database CRUD tests
│   ├── test_calendar.py           # Calendar API tests
│   ├── test_extractor.py          # Text extraction tests
│   ├── test_meeting_conversation.py  # Conversation classification tests
│   ├── test_minutes_generator.py  # Minutes prompt tests
│   ├── test_admin.py              # Admin endpoint tests
│   ├── test_tts.py                # TTS tests
│   ├── test_knowledge.py          # Knowledge base tests
│   ├── test_persona.py            # Persona tests
│   └── test_conversation.py       # Conversation tests
├── docker/
│   └── Dockerfile                 # Cloud Run image
├── requirements.txt
├── requirements-dev.txt
└── .env.example
```

## Architecture

```
Google Calendar ──OAuth2──> [Calendar Sync] ──> meetings DB
                                                    │
User: "この会議にAI出席させて" ──> ai_enabled=1     │
                                                    │
[Scheduler] ── 60秒ごとチェック ── 開始2分前に自動参加
                                                    │
Recall.ai Bot joins Google Meet ←──────────────────┘
       │
       │ Webhook: transcript.data
       ▼
[Enhanced Response Pipeline]
  1. 会話ログをDBに保存
  2. 会議の添付資料をコンテキストに注入
  3. Gemini: 回答可能 → [ANSWERED] 直接回答
            判断必要 → [TAKEN_BACK] 「持ち帰ります」
  4. TTS → 音声で会議に応答
  5. 分類結果をDBに記録
       │
[Meeting Ends]
       │
       ▼
[Minutes Generator] ── Gemini ──> 構造化議事録
       │
       ├── 管理画面で表示・編集
       └── Google Docsにエクスポート
```

## Endpoints

### Auth (`/auth/google/`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/auth/google/login` | Google OAuth同意画面へリダイレクト |
| GET | `/auth/google/callback` | OAuthコールバック処理 |
| GET | `/auth/google/status` | 認証状態確認 |
| POST | `/auth/google/revoke` | トークン無効化 |

### Calendar (`/calendar/`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/calendar/events` | 今後の会議一覧（`days_ahead`指定可） |
| POST | `/calendar/events/{event_id}/enable-ai` | AI出席を有効化 |
| POST | `/calendar/events/{event_id}/disable-ai` | AI出席を無効化 |
| POST | `/calendar/sync` | カレンダー強制再同期 |

### Materials (`/meetings/{meeting_id}/materials/`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/meetings/{meeting_id}/materials` | 資料一覧 |
| POST | `/meetings/{meeting_id}/materials/upload` | PDF/MD/TXTアップロード |
| POST | `/meetings/{meeting_id}/materials/drive` | Google Driveリンク |
| DELETE | `/meetings/{meeting_id}/materials/{id}` | 資料削除 |

### Minutes (`/meetings/{meeting_id}/minutes/`)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/meetings/{meeting_id}/minutes/generate` | 議事録生成（Gemini） |
| GET | `/meetings/{meeting_id}/minutes` | 議事録表示 |
| PUT | `/meetings/{meeting_id}/minutes` | 議事録編集 |
| POST | `/meetings/{meeting_id}/minutes/export` | Google Docsエクスポート |

### Bot Control (`/bot/`)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/bot/join` | Botを会議に参加させる（`meeting_id`指定で資料連携） |
| GET | `/bot/{bot_id}/status` | Bot状態取得 |
| POST | `/bot/{bot_id}/leave` | Botを退出させる |
| POST | `/bot/webhook/transcript` | Recall.aiリアルタイム文字起こしWebhook |

### Admin Management (`/admin/`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/admin/status` | システム状態 |
| GET | `/admin/profile` | ペルソナプロファイル取得 |
| PUT | `/admin/profile` | ペルソナプロファイル更新 |
| GET | `/admin/settings` | TTS/Bot設定取得 |
| PUT | `/admin/settings` | TTS/Bot設定更新 |
| POST | `/admin/tts/preview` | 音声プレビュー |
| GET | `/admin/knowledge` | ナレッジ文書一覧 |
| GET | `/admin/knowledge/{filename}` | 文書内容取得 |
| PUT | `/admin/knowledge/{filename}` | 文書作成/更新 |
| DELETE | `/admin/knowledge/{filename}` | 文書削除 |

### Core API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness probe |
| GET | `/health/ready` | Dependency readiness check |
| GET | `/metrics` | Request metrics |
| POST | `/transcribe` | 音声ファイル → 文字起こし |
| POST | `/chat` | テキスト → Gemini応答（SSE対応） |
| POST | `/meeting-proxy` | 音声 → 文字起こし → Gemini（SSE対応） |

### Web UI

- Admin dashboard: `http://localhost:8000/static/index.html` (or `/`)
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Prerequisites

1. Python 3.9+
2. GCP project with APIs enabled:
   - Speech-to-Text API
   - Vertex AI API
   - Cloud Text-to-Speech API
   - Google Calendar API
   - Google Drive API
   - Google Docs API
3. GCP credentials with roles:
   - `roles/speech.client`
   - `roles/aiplatform.user`
   - `roles/texttospeech.client`
4. Google OAuth2 client credentials (for Calendar/Drive/Docs integration)
5. (Optional) [Recall.ai](https://recall.ai) API key for Google Meet bot integration

## Setup

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your values
```

### 3. Set up Google OAuth2 (for Calendar/Drive/Docs)

1. [Google Cloud Console](https://console.cloud.google.com/apis/credentials) でOAuth 2.0クライアントIDを作成
2. アプリケーションの種類: **ウェブアプリケーション**
3. 承認済みリダイレクトURI: `http://localhost:8000/auth/google/callback`
4. `.env`に設定:

```bash
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback
```

5. APIライブラリで以下を有効化:
   - Google Calendar API
   - Google Drive API
   - Google Docs API

### 4. Authenticate with GCP (for Speech-to-Text, Vertex AI, TTS)

```bash
gcloud auth application-default login
```

### 5. Run the API

```bash
uvicorn main:app --reload
```

### 6. Connect Google Account

1. ブラウザで `http://localhost:8000` を開く
2. ダッシュボードの「Googleアカウントを連携」をクリック
3. Google認証を完了
4. カレンダータブで会議一覧が表示される

## Configuration

Core settings in `.env`:

```bash
# GCP
GCP_PROJECT_ID=your-project-id
GCP_LOCATION=us-central1
GEMINI_MODEL=gemini-1.5-pro

# Auth (optional - skipped when unset)
API_KEY=your-api-key

# Google OAuth2 (Calendar, Drive, Docs)
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback

# Database
DB_PATH=data/meetings.db

# Materials
MATERIALS_UPLOAD_DIR=data/materials

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

## Database

SQLite database with 5 tables:

| Table | Purpose |
|-------|---------|
| `oauth_tokens` | Google OAuth2トークン |
| `meetings` | カレンダーから取得した会議情報 |
| `materials` | 会議に紐付いた資料（アップロード/Drive） |
| `conversation_log` | 会話ログ（発話者、回答/持ち帰り分類） |
| `minutes` | 構造化議事録（JSON + Markdown） |

Data is stored in `data/meetings.db` (configurable via `DB_PATH`).

## Meeting Lifecycle

1. **カレンダー同期**: OAuth2連携後、自動的にGoogle Calendarからイベントを取得
2. **AI有効化**: 管理画面でトグルを切り替え → `ai_enabled=1`
3. **資料共有**: 会議に資料をアップロード or Google Driveからリンク
4. **自動参加**: スケジューラーが開始2分前にRecall.ai Botを送信
5. **会議中**: 資料ベースで質問応答、回答/持ち帰りを自動分類してDB記録
6. **議事録生成**: 会議後にGeminiで構造化議事録を生成
7. **エクスポート**: Google Docsに議事録をエクスポート

## Security Controls

- Optional API key auth with `X-API-Key` header
- Google OAuth2 with PKCE for Calendar/Drive/Docs access
- Audio type validation (MIME + extension + magic bytes)
- Upload size limit (`MAX_AUDIO_SIZE_BYTES`, default 10 MB)
- Material upload size limit (20 MB)
- Text input size limit (`MAX_INPUT_CHARS`, default 20,000)
- Request ID on every response (`X-Request-ID`)
- Generic error responses (no stack traces leaked)
- Knowledge filename validation (path traversal protection)
- SQL injection prevention via parameterized queries + allowlisted keys

## Tests

```bash
pip install -r requirements-dev.txt
GCP_PROJECT_ID=local-test pytest -q
```

84 tests covering: API guards, bot endpoints, database CRUD, calendar sync, text extraction, conversation classification, minutes generation, admin endpoints, TTS, knowledge base, persona, and conversation management.

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

Python 3.9+ | FastAPI | Pydantic | GCP Speech-to-Text | Vertex AI (Gemini) | Cloud Text-to-Speech | Google Calendar/Drive/Docs API | Recall.ai | SQLite (aiosqlite) | PyPDF2 | Docker | ruff | bandit
