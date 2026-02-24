"""Tests for bot.audio_bridge.AudioBridge."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from config import settings


def _set_default_test_settings() -> None:
    settings.meeting_mode = "local"
    settings.blackhole_capture_device = "BlackHole 2ch"
    settings.blackhole_playback_device = "BlackHole 16ch"
    settings.local_audio_sample_rate = 16000
    settings.local_audio_chunk_ms = 100
    settings.api_key = None


def test_resample_same_rate() -> None:
    """Resampling with same rate returns identical data."""
    from bot.audio_bridge import _resample

    data = np.array([0.0, 0.5, 1.0, 0.5, 0.0], dtype=np.float32)
    result = _resample(data, 16000, 16000)
    np.testing.assert_array_almost_equal(result, data)


def test_resample_downsample() -> None:
    """Downsampling produces fewer samples."""
    from bot.audio_bridge import _resample

    data = np.ones(480, dtype=np.float32)
    result = _resample(data, 48000, 16000)
    assert len(result) == 160


def test_resample_upsample() -> None:
    """Upsampling produces more samples."""
    from bot.audio_bridge import _resample

    data = np.ones(160, dtype=np.float32)
    result = _resample(data, 16000, 48000)
    assert len(result) == 480


def test_find_device_index_found() -> None:
    """_find_device_index returns correct index when device exists."""
    mock_devices = [
        {"name": "Built-in Output", "max_input_channels": 0, "max_output_channels": 2},
        {"name": "BlackHole 2ch", "max_input_channels": 2, "max_output_channels": 2},
        {"name": "BlackHole 16ch", "max_input_channels": 16, "max_output_channels": 16},
    ]

    with patch("bot.audio_bridge.sd.query_devices", return_value=mock_devices):
        from bot.audio_bridge import _find_device_index

        assert _find_device_index("BlackHole 2ch", "input") == 1
        assert _find_device_index("BlackHole 16ch", "output") == 2


def test_find_device_index_not_found() -> None:
    """_find_device_index returns None when device doesn't exist."""
    mock_devices = [
        {"name": "Built-in Output", "max_input_channels": 0, "max_output_channels": 2},
    ]

    with patch("bot.audio_bridge.sd.query_devices", return_value=mock_devices):
        from bot.audio_bridge import _find_device_index

        assert _find_device_index("BlackHole 2ch", "input") is None


@pytest.mark.asyncio
async def test_audio_bridge_callback() -> None:
    """AudioBridge forwards captured audio to the callback."""
    _set_default_test_settings()

    received_chunks: list[bytes] = []

    async def on_chunk(data: bytes) -> None:
        received_chunks.append(data)

    mock_devices = [
        {"name": "BlackHole 2ch", "max_input_channels": 2, "max_output_channels": 2},
        {"name": "BlackHole 16ch", "max_input_channels": 16, "max_output_channels": 16},
    ]

    with (
        patch("bot.audio_bridge.sd.query_devices") as mock_qd,
        patch("bot.audio_bridge.sd.InputStream") as mock_input,
        patch("bot.audio_bridge.sd.OutputStream") as mock_output,
    ):
        # query_devices with no args returns list, with args returns dict
        def _query_side_effect(*args, **kwargs):
            if args:
                idx = args[0]
                return mock_devices[idx] | {"default_samplerate": 48000.0}
            return mock_devices

        mock_qd.side_effect = _query_side_effect

        mock_stream = MagicMock()
        mock_input.return_value = mock_stream
        mock_out_stream = MagicMock()
        mock_output.return_value = mock_out_stream

        from bot.audio_bridge import AudioBridge

        bridge = AudioBridge(
            capture_device="BlackHole 2ch",
            playback_device="BlackHole 16ch",
            sample_rate=16000,
            chunk_ms=100,
        )
        await bridge.start(on_chunk)

        # Verify streams were opened
        mock_input.assert_called_once()
        mock_stream.start.assert_called_once()
        mock_output.assert_called_once()
        mock_out_stream.start.assert_called_once()

        await bridge.stop()


@pytest.mark.asyncio
async def test_play_audio_sends_to_device() -> None:
    """play_audio writes audio data to the playback stream."""
    _set_default_test_settings()

    mock_stream = MagicMock()
    mock_devices = [
        {"name": "BlackHole 16ch", "max_input_channels": 16, "max_output_channels": 16},
    ]

    with patch("bot.audio_bridge.sd.query_devices") as mock_qd:
        mock_qd.side_effect = lambda *a, **kw: (
            (mock_devices[a[0]] | {"default_samplerate": 48000.0}) if a else mock_devices
        )

        from bot.audio_bridge import AudioBridge

        bridge = AudioBridge()
        bridge._playback_stream = mock_stream
        bridge._playback_idx = 0
        bridge._running = True

        # Create test PCM data (1 second of silence at 16kHz, 16-bit)
        pcm_data = np.zeros(16000, dtype=np.int16).tobytes()
        bridge.play_audio(pcm_data, 16000)

        mock_stream.write.assert_called_once()
