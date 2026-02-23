"""Tests for bot/audio_utils.py — PCM ↔ MP3 conversion."""

from __future__ import annotations

import base64
import struct

from bot.audio_utils import decode_b64_pcm, pcm_to_mp3_b64


def _make_pcm_silence(num_samples: int = 480, channels: int = 1) -> bytes:
    """Generate silent PCM 16-bit samples."""
    return struct.pack(f"<{num_samples * channels}h", *([0] * num_samples * channels))


def test_pcm_to_mp3_b64_returns_base64_string() -> None:
    pcm = _make_pcm_silence(4800)
    result = pcm_to_mp3_b64(pcm, sample_rate=24000, channels=1)
    # Result should be valid base64
    decoded = base64.b64decode(result)
    assert len(decoded) > 0


def test_pcm_to_mp3_b64_output_is_mp3() -> None:
    pcm = _make_pcm_silence(4800)
    result = pcm_to_mp3_b64(pcm, sample_rate=24000)
    mp3_bytes = base64.b64decode(result)
    # MP3 starts with ID3 tag or sync word
    assert mp3_bytes[:3] == b"ID3" or (mp3_bytes[0] == 0xFF and (mp3_bytes[1] & 0xE0) == 0xE0)


def test_pcm_to_mp3_b64_custom_sample_rate() -> None:
    pcm = _make_pcm_silence(1600)
    result = pcm_to_mp3_b64(pcm, sample_rate=16000)
    decoded = base64.b64decode(result)
    assert len(decoded) > 0


def test_decode_b64_pcm_roundtrip() -> None:
    original = b"\x00\x01\x02\x03\x04\x05"
    encoded = base64.b64encode(original).decode("ascii")
    result = decode_b64_pcm(encoded)
    assert result == original


def test_decode_b64_pcm_empty() -> None:
    encoded = base64.b64encode(b"").decode("ascii")
    result = decode_b64_pcm(encoded)
    assert result == b""
