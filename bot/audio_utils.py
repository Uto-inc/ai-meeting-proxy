"""PCM ↔ MP3 conversion utilities for Gemini Live API audio pipeline."""

from __future__ import annotations

import base64
import io
import logging

from pydub import AudioSegment

logger = logging.getLogger("meeting-proxy.audio")


def pcm_to_mp3_b64(pcm_bytes: bytes, sample_rate: int = 24000, channels: int = 1) -> str:
    """Convert raw PCM bytes to a base64-encoded MP3 string.

    Args:
        pcm_bytes: Raw PCM 16-bit signed little-endian audio data.
        sample_rate: Sample rate of the PCM data (default 24000 for Gemini output).
        channels: Number of audio channels (default 1 / mono).

    Returns:
        Base64-encoded MP3 string suitable for Recall.ai output_audio API.
    """
    segment = AudioSegment(
        data=pcm_bytes,
        sample_width=2,  # 16-bit
        frame_rate=sample_rate,
        channels=channels,
    )
    buf = io.BytesIO()
    segment.export(buf, format="mp3", bitrate="64k")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def decode_b64_pcm(b64_data: str) -> bytes:
    """Decode a base64-encoded PCM payload to raw bytes.

    Args:
        b64_data: Base64-encoded string from Recall.ai audio_mixed_raw.data.

    Returns:
        Raw PCM bytes.
    """
    return base64.b64decode(b64_data)
