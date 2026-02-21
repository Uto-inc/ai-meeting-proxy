"""Google Cloud Text-to-Speech wrapper for Japanese voice synthesis."""

import base64
import logging

from google.cloud import texttospeech

from config import settings

logger = logging.getLogger("meeting-proxy.tts")

_tts_client: texttospeech.TextToSpeechClient | None = None


def init_tts_client() -> None:
    """Initialize the TTS client. Called at startup."""
    global _tts_client
    try:
        _tts_client = texttospeech.TextToSpeechClient()
        logger.info("Cloud TTS client initialized")
    except Exception:
        logger.exception("Failed to initialize Cloud TTS client")
        _tts_client = None


def synthesize_japanese(text: str) -> bytes:
    """Synthesize Japanese text to MP3 audio bytes."""
    if _tts_client is None:
        raise RuntimeError("Cloud TTS client is not initialized")

    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code="ja-JP",
        name=settings.tts_voice_name,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=settings.tts_speaking_rate,
    )

    response = _tts_client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config,
    )

    logger.info("Synthesized %d bytes of audio for %d chars", len(response.audio_content), len(text))
    return response.audio_content


def synthesize_to_base64(text: str) -> str:
    """Synthesize Japanese text and return base64-encoded MP3 (for Recall.ai)."""
    audio_bytes = synthesize_japanese(text)
    return base64.b64encode(audio_bytes).decode("ascii")


def is_available() -> bool:
    """Check if the TTS client is initialized."""
    return _tts_client is not None
