# AI Meeting Proxy - Vercel + GCP PoC

FastAPI proof-of-concept for an AI meeting proxy pipeline:
- Speech-to-Text transcription (GCP Speech-to-Text)
- Dialogue generation/summarization (Vertex AI Gemini)
- End-to-end endpoint for `audio -> transcript -> AI response`

## Project Structure

- `main.py`: FastAPI app and endpoints
- `config.py`: environment-driven settings
- `requirements.txt`: Python dependencies
- `.env.example`: environment variable template
- `docker/Dockerfile`: container image for Cloud Run

## Endpoints

- `POST /transcribe`
  - Multipart file upload (`audio_file`) for WAV/MP3
  - Returns transcription text
- `POST /chat`
  - Form fields: `message`, optional `meeting_context`, optional `stream`
  - Returns Gemini response, supports SSE streaming when `stream=true`
- `POST /meeting-proxy`
  - Form fields: `audio_file`, optional `meeting_context`, optional `stream`
  - Full pipeline response with transcript + Gemini output
- `POST /streaming/transcribe`
  - Placeholder for real-time streaming session setup
- `GET /health`
  - Basic health check
- `GET /health/ready`
  - Dependency readiness (Speech/Vertex client state)
- `GET /metrics`
  - Basic request/error/latency metrics (requires API key when enabled)

FastAPI auto docs:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Prerequisites

1. Python 3.11+
2. GCP project with APIs enabled:
   - Speech-to-Text API
   - Vertex AI API
3. Service account with roles (minimum PoC):
   - `roles/speech.client`
   - `roles/aiplatform.user`

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

3. Authenticate with GCP credentials.

Option A: Service account key file (local PoC)
```bash
export GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/service-account.json
```

Option B: ADC via gcloud
```bash
gcloud auth application-default login
```

4. Run the API.

```bash
uvicorn main:app --reload
```

## Security Controls

- Optional API key auth with `X-API-Key` header (`API_KEY` in env)
- Audio type validation by MIME + extension + file signature (WAV/MP3 only)
- Upload size limit (`MAX_AUDIO_SIZE_BYTES`)
- Text input size limit (`MAX_INPUT_CHARS`)
- Request ID on every response (`X-Request-ID`)
- Generic internal error responses (no stack traces leaked to clients)

## Example Usage

### 1) Transcribe audio

```bash
curl -X POST "http://localhost:8000/transcribe" \
  -H "X-API-Key: <your-api-key>" \
  -F "audio_file=@./sample.wav"
```

### 2) Chat with Gemini (non-streaming)

```bash
curl -X POST "http://localhost:8000/chat" \
  -H "X-API-Key: <your-api-key>" \
  -F 'message=Summarize today meeting decisions and actions.' \
  -F 'meeting_context=Weekly product sync for AI meeting proxy project.'
```

### 3) Chat with Gemini (SSE streaming)

```bash
curl -N -X POST "http://localhost:8000/chat" \
  -H "X-API-Key: <your-api-key>" \
  -F 'message=Create concise executive summary from this transcript text.' \
  -F 'stream=true'
```

### 4) Full meeting proxy pipeline

```bash
curl -X POST "http://localhost:8000/meeting-proxy" \
  -H "X-API-Key: <your-api-key>" \
  -F "audio_file=@./sample.mp3" \
  -F 'meeting_context=Customer discovery call with enterprise client.'
```

### 5) Full pipeline with streaming AI response

```bash
curl -N -X POST "http://localhost:8000/meeting-proxy" \
  -H "X-API-Key: <your-api-key>" \
  -F "audio_file=@./sample.wav" \
  -F 'meeting_context=Engineering sprint planning' \
  -F 'stream=true'
```

## Cloud Run Deployment

Build and deploy from project root:

```bash
gcloud run deploy ai-meeting-proxy-poc \
  --source . \
  --region us-central1 \
  --allow-unauthenticated
```

Or build with Dockerfile:

```bash
docker build -f docker/Dockerfile -t ai-meeting-proxy-poc:latest .
```

## Tests

```bash
pip install -r requirements-dev.txt
GCP_PROJECT_ID=local-test pytest -q
```

## CI/CD Readiness

- GitHub Actions workflow: `.github/workflows/ci.yml`
- Runs unit tests on push / pull request
- Ready to extend with lint, SAST, and container scan steps

## Notes

- This implementation is intentionally PoC-level and synchronous for transcription.
- `POST /streaming/transcribe` is scaffolded for future low-latency, chunked audio transport (WebSocket/gRPC stream).
- For production, prefer Workload Identity or attached service accounts over static key files.
