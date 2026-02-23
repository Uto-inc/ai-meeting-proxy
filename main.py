from __future__ import annotations

import hmac
import json
import logging
import os
import threading
import time
import uuid
from collections import Counter
from collections.abc import Generator
from contextlib import asynccontextmanager
from typing import Any

import google.auth
import vertexai
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from google.api_core.exceptions import GoogleAPIError
from google.cloud import speech
from vertexai.generative_models import GenerativeModel

from auth.router import router as auth_router
from bot.admin_router import router as admin_router
from bot.router import router as bot_router
from calendar_sync.router import router as calendar_router
from config import settings
from materials.router import router as materials_router
from minutes.router import router as minutes_router

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("meeting-proxy")

speech_client: speech.SpeechClient | None = None
vertex_model: GenerativeModel | None = None
metrics_lock = threading.Lock()
metrics: dict[str, Any] = {
    "requests_total": 0,
    "errors_total": 0,
    "latency_ms_sum": 0.0,
    "path_count": Counter(),
}

ALLOWED_AUDIO_TYPES = {
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/mpeg",
    "audio/mp3",
}
ALLOWED_AUDIO_EXTENSIONS = {"wav", "mp3"}


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    """Application lifespan: initialize DB, GCP services, and avatar components."""
    global speech_client, vertex_model

    # Initialize database
    try:
        from db.repository import Repository
        from db.schema import init_db

        os.makedirs(os.path.dirname(settings.db_path) or ".", exist_ok=True)
        db = await init_db(settings.db_path)
        app.state.db = db
        app.state.repo = Repository(db)
        logger.info("Database initialized")
    except Exception:
        logger.exception("Failed to initialize database")
        app.state.db = None
        app.state.repo = None

    # Initialize GCP credentials
    try:
        _, project = google.auth.default()
        logger.info("GCP credentials detected (project=%s)", project)
    except Exception as exc:
        logger.warning("Could not validate GCP credentials at startup: %s", exc)

    # Initialize Speech-to-Text
    try:
        speech_client = speech.SpeechClient()
        logger.info("Speech-to-Text client initialized")
    except Exception:
        logger.exception("Failed to initialize Speech-to-Text client")
        speech_client = None

    # Initialize Vertex AI
    try:
        vertexai.init(project=settings.gcp_project_id, location=settings.gcp_location)
        vertex_model = GenerativeModel(settings.gemini_model)
        logger.info(
            "Vertex AI initialized (project=%s, location=%s, model=%s)",
            settings.gcp_project_id,
            settings.gcp_location,
            settings.gemini_model,
        )
    except Exception:
        logger.exception("Failed to initialize Vertex AI")
        vertex_model = None

    # Initialize TTS client
    try:
        from bot.tts import init_tts_client

        init_tts_client()
    except Exception:
        logger.exception("Failed to initialize Cloud TTS client")

    # Initialize avatar components
    try:
        from bot.router import init_avatar_components

        init_avatar_components()
    except Exception:
        logger.exception("Failed to initialize avatar components")

    # Start meeting scheduler
    if app.state.repo:
        try:
            from calendar_sync.scheduler import start_scheduler

            start_scheduler(app.state.repo)
        except Exception:
            logger.exception("Failed to start meeting scheduler")

    yield

    # Shutdown
    from calendar_sync.scheduler import stop_scheduler

    stop_scheduler()

    if app.state.db:
        await app.state.db.close()
        logger.info("Database connection closed")


app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    description="AI Meeting Proxy – Calendar, Materials, Minutes, and real-time meeting participation",
    docs_url="/docs" if settings.enable_docs else None,
    redoc_url="/redoc" if settings.enable_docs else None,
    openapi_url="/openapi.json" if settings.enable_docs else None,
    lifespan=lifespan,
)

app.include_router(auth_router)
app.include_router(bot_router, prefix="/bot")
app.include_router(admin_router)
app.include_router(calendar_router)
app.include_router(materials_router)
app.include_router(minutes_router)


def _detect_audio_encoding(filename: str) -> speech.RecognitionConfig.AudioEncoding:
    ext = filename.lower().split(".")[-1] if "." in filename else ""
    if ext == "wav":
        return speech.RecognitionConfig.AudioEncoding.LINEAR16
    if ext == "mp3":
        return speech.RecognitionConfig.AudioEncoding.MP3
    raise HTTPException(status_code=400, detail="Only WAV and MP3 files are supported")


def _transcribe_audio_bytes(audio_bytes: bytes, filename: str) -> str:
    global speech_client
    if speech_client is None:
        raise HTTPException(status_code=503, detail="Speech-to-Text client is not initialized")

    encoding = _detect_audio_encoding(filename)
    config = speech.RecognitionConfig(
        encoding=encoding,
        language_code=settings.stt_language_code,
        model=settings.stt_model,
        enable_automatic_punctuation=True,
    )
    audio = speech.RecognitionAudio(content=audio_bytes)

    try:
        response = speech_client.recognize(config=config, audio=audio, timeout=60)
    except GoogleAPIError as exc:
        logger.exception("Speech-to-Text API call failed")
        raise HTTPException(status_code=502, detail="Speech-to-Text request failed") from exc

    transcripts = [result.alternatives[0].transcript for result in response.results if result.alternatives]
    transcript = " ".join(t.strip() for t in transcripts if t.strip())
    if not transcript:
        raise HTTPException(status_code=422, detail="No transcription result returned")
    return transcript


def _build_meeting_prompt(transcript: str, meeting_context: str | None = None) -> str:
    context = meeting_context or (
        "You are an AI meeting proxy. Summarize key points, identify action items "
        "with owners when possible, and list open questions."
    )
    return (
        "Meeting Context:\n"
        f"{context}\n\n"
        "Transcript:\n"
        f"{transcript}\n\n"
        "Return:\n"
        "1) concise summary\n"
        "2) action items\n"
        "3) risks/blockers\n"
        "4) follow-up questions"
    )


def _generate_text(prompt: str) -> str:
    global vertex_model
    if vertex_model is None:
        raise HTTPException(status_code=503, detail="Gemini model is not initialized")

    try:
        response = vertex_model.generate_content(prompt)
    except GoogleAPIError as exc:
        logger.exception("Vertex AI API call failed")
        raise HTTPException(status_code=502, detail="Gemini request failed") from exc

    text = (response.text or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="Gemini returned an empty response")
    return text


def _stream_gemini_sse(prompt: str) -> Generator[str, None, None]:
    global vertex_model
    if vertex_model is None:
        yield "event: error\ndata: Gemini model is not initialized\n\n"
        return

    try:
        for chunk in vertex_model.generate_content(prompt, stream=True):
            text = chunk.text or ""
            if text:
                payload = {"delta": text}
                yield f"data: {json.dumps(payload)}\n\n"
        yield "event: done\ndata: {}\n\n"
    except GoogleAPIError:
        logger.exception("Streaming Gemini response failed")
        yield f"event: error\ndata: {json.dumps({'message': 'Gemini streaming failed'})}\n\n"


def _increment_metric(path: str, latency_ms: float, errored: bool) -> None:
    with metrics_lock:
        metrics["requests_total"] += 1
        metrics["latency_ms_sum"] += latency_ms
        metrics["path_count"][path] += 1
        if errored:
            metrics["errors_total"] += 1


def _is_wav(audio_bytes: bytes) -> bool:
    return len(audio_bytes) >= 12 and audio_bytes[:4] == b"RIFF" and audio_bytes[8:12] == b"WAVE"


def _is_mp3(audio_bytes: bytes) -> bool:
    return audio_bytes.startswith(b"ID3") or (
        len(audio_bytes) >= 2 and audio_bytes[0] == 0xFF and (audio_bytes[1] & 0xE0) == 0xE0
    )


def _validate_audio_file(audio_file: UploadFile, audio_bytes: bytes) -> None:
    filename = audio_file.filename or ""
    ext = filename.lower().split(".")[-1] if "." in filename else ""
    if audio_file.content_type not in ALLOWED_AUDIO_TYPES or ext not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported file type. Use WAV or MP3")
    if ext == "wav" and not _is_wav(audio_bytes):
        raise HTTPException(status_code=400, detail="Invalid WAV file signature")
    if ext == "mp3" and not _is_mp3(audio_bytes):
        raise HTTPException(status_code=400, detail="Invalid MP3 file signature")


def _normalize_text_input(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail=f"{field_name} cannot be empty")
    if len(normalized) > settings.max_input_chars:
        raise HTTPException(
            status_code=413,
            detail=f"{field_name} too large. Max chars: {settings.max_input_chars}",
        )
    return normalized


async def _read_upload_limited(audio_file: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await audio_file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > settings.max_audio_size_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Audio file too large. Max bytes: {settings.max_audio_size_bytes}",
            )
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    return b"".join(chunks)


def _auth_guard(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    if not settings.api_key:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@app.middleware("http")
async def request_metrics_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    start = time.perf_counter()
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    errored = False
    try:
        response = await call_next(request)
    except Exception:
        errored = True
        raise
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        _increment_metric(request.url.path, elapsed_ms, errored)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    logger.warning("Request validation failed (request_id=%s): %s", request.state.request_id, exc)
    return JSONResponse(status_code=422, content={"detail": "Invalid request payload"})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error (request_id=%s)", request.state.request_id)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def readiness() -> JSONResponse:
    ready = speech_client is not None and vertex_model is not None
    status = 200 if ready else 503
    return JSONResponse(
        status_code=status,
        content={
            "status": "ready" if ready else "not_ready",
            "speech_client": speech_client is not None,
            "vertex_model": vertex_model is not None,
            "project": settings.gcp_project_id,
            "location": settings.gcp_location,
            "env": settings.env,
        },
    )


@app.get("/metrics")
def metrics_snapshot(_: None = Depends(_auth_guard)) -> JSONResponse:
    with metrics_lock:
        requests_total = metrics["requests_total"]
        avg_latency_ms = metrics["latency_ms_sum"] / requests_total if requests_total else 0.0
        data = {
            "requests_total": requests_total,
            "errors_total": metrics["errors_total"],
            "average_latency_ms": round(avg_latency_ms, 2),
            "path_count": dict(metrics["path_count"]),
        }
    return JSONResponse(data)


@app.post("/transcribe")
async def transcribe(
    audio_file: UploadFile = File(...),
    _: None = Depends(_auth_guard),
) -> JSONResponse:
    audio_bytes = await _read_upload_limited(audio_file)
    _validate_audio_file(audio_file, audio_bytes)
    transcript = await run_in_threadpool(_transcribe_audio_bytes, audio_bytes, audio_file.filename or "")
    return JSONResponse({"transcript": transcript})


@app.post("/chat", response_model=None)
async def chat(
    message: str = Form(...),
    meeting_context: str | None = Form(default=None),
    stream: bool = Form(default=False),
    _: None = Depends(_auth_guard),
) -> JSONResponse | StreamingResponse:
    prompt = _build_meeting_prompt(
        _normalize_text_input(message, "message"),
        _normalize_text_input(meeting_context, "meeting_context") if meeting_context else None,
    )

    if stream:
        return StreamingResponse(
            _stream_gemini_sse(prompt),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    response_text = await run_in_threadpool(_generate_text, prompt)
    return JSONResponse({"response": response_text})


@app.post("/meeting-proxy", response_model=None)
async def meeting_proxy(
    audio_file: UploadFile = File(...),
    meeting_context: str | None = Form(default=None),
    stream: bool = Form(default=False),
    _: None = Depends(_auth_guard),
) -> JSONResponse | StreamingResponse:
    audio_bytes = await _read_upload_limited(audio_file)
    _validate_audio_file(audio_file, audio_bytes)
    transcript = await run_in_threadpool(_transcribe_audio_bytes, audio_bytes, audio_file.filename or "")
    prompt = _build_meeting_prompt(
        transcript,
        _normalize_text_input(meeting_context, "meeting_context") if meeting_context else None,
    )

    if stream:

        def event_stream() -> Generator[str, None, None]:
            yield f"event: transcript\ndata: {json.dumps({'transcript': transcript})}\n\n"
            yield from _stream_gemini_sse(prompt)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    response_text = await run_in_threadpool(_generate_text, prompt)
    return JSONResponse({"transcript": transcript, "response": response_text})


@app.post("/streaming/transcribe")
async def streaming_transcribe_prep(_: None = Depends(_auth_guard)) -> JSONResponse:
    return JSONResponse(
        {
            "status": "prepared",
            "message": (
                "Placeholder endpoint for real-time streaming transcription session setup. "
                "Implement bidirectional WebSocket/audio chunk transport in next iteration."
            ),
        }
    )


@app.get("/")
def root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/static/index.html")


app.mount("/static", StaticFiles(directory="static", html=True), name="static")
