"""Audio bridge using sounddevice for BlackHole virtual audio capture/playback."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import numpy as np
import sounddevice as sd

from config import settings

logger = logging.getLogger("meeting-proxy.audio-bridge")

# BlackHole typically operates at 48kHz; Gemini expects 16kHz mono PCM
_BLACKHOLE_NATIVE_RATE = 48000


def _find_device_index(name: str, kind: str) -> int | None:
    """Find a sounddevice device index by name substring.

    Args:
        name: Device name substring to search for.
        kind: "input" or "output".

    Returns:
        Device index or None if not found.
    """
    devices = sd.query_devices()
    for i, dev in enumerate(devices):
        if name.lower() in dev["name"].lower():
            if kind == "input" and dev["max_input_channels"] > 0:
                return i
            if kind == "output" and dev["max_output_channels"] > 0:
                return i
    return None


def _resample(data: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Simple linear interpolation resampling.

    Args:
        data: 1D float32 numpy array.
        src_rate: Source sample rate.
        dst_rate: Destination sample rate.

    Returns:
        Resampled 1D float32 numpy array.
    """
    if src_rate == dst_rate:
        return data
    ratio = dst_rate / src_rate
    n_samples = int(len(data) * ratio)
    indices = np.linspace(0, len(data) - 1, n_samples)
    return np.interp(indices, np.arange(len(data)), data).astype(np.float32)


class AudioBridge:
    """Captures audio from BlackHole and plays back to BlackHole.

    Capture: BlackHole 2ch (Meet audio output) -> PCM 16kHz mono -> callback
    Playback: PCM audio -> BlackHole 16ch (Meet microphone input)
    """

    def __init__(
        self,
        capture_device: str | None = None,
        playback_device: str | None = None,
        sample_rate: int | None = None,
        chunk_ms: int | None = None,
    ) -> None:
        self._capture_device_name = capture_device or settings.blackhole_capture_device
        self._playback_device_name = playback_device or settings.blackhole_playback_device
        self._target_rate = sample_rate or settings.local_audio_sample_rate
        self._chunk_ms = chunk_ms or settings.local_audio_chunk_ms

        self._capture_stream: sd.InputStream | None = None
        self._playback_stream: sd.OutputStream | None = None
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._audio_queue: asyncio.Queue[bytes] | None = None
        self._consumer_task: asyncio.Task[None] | None = None

        # Device indices (resolved at start)
        self._capture_idx: int | None = None
        self._playback_idx: int | None = None

    async def start(self, on_audio_chunk: Callable[[bytes], Awaitable[None]]) -> None:
        """Start audio capture and set up playback.

        Args:
            on_audio_chunk: Async callback receiving PCM 16kHz 16-bit mono bytes.
        """
        self._loop = asyncio.get_running_loop()
        self._audio_queue = asyncio.Queue()
        self._running = True

        # Resolve device indices
        self._capture_idx = _find_device_index(self._capture_device_name, "input")
        if self._capture_idx is None:
            raise RuntimeError(f"Capture device not found: {self._capture_device_name}")
        logger.info("Capture device: %s (index=%d)", self._capture_device_name, self._capture_idx)

        self._playback_idx = _find_device_index(self._playback_device_name, "output")
        if self._playback_idx is None:
            raise RuntimeError(f"Playback device not found: {self._playback_device_name}")
        logger.info("Playback device: %s (index=%d)", self._playback_device_name, self._playback_idx)

        # Determine native sample rate for capture device
        dev_info = sd.query_devices(self._capture_idx, "input")
        native_rate = int(dev_info["default_samplerate"])
        blocksize = int(native_rate * self._chunk_ms / 1000)

        # Audio callback runs in a separate thread
        def _capture_callback(
            indata: np.ndarray,
            frames: int,
            time_info: Any,
            status: sd.CallbackFlags,
        ) -> None:
            if status:
                logger.debug("Capture status: %s", status)
            if not self._running:
                return

            # Convert to mono float32
            audio = indata[:, 0].copy() if indata.ndim > 1 else indata.flatten().copy()

            # Resample to target rate
            audio = _resample(audio, native_rate, self._target_rate)

            # Convert float32 [-1.0, 1.0] to int16 PCM bytes
            pcm_int16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)
            pcm_bytes = pcm_int16.tobytes()

            # Thread-safe put to asyncio queue
            if self._loop is not None and self._audio_queue is not None:
                self._loop.call_soon_threadsafe(self._audio_queue.put_nowait, pcm_bytes)

        self._capture_stream = sd.InputStream(
            device=self._capture_idx,
            samplerate=native_rate,
            channels=1,
            dtype="float32",
            blocksize=blocksize,
            callback=_capture_callback,
        )
        self._capture_stream.start()
        logger.info(
            "Audio capture started (rate=%d, blocksize=%d, target=%dHz)",
            native_rate,
            blocksize,
            self._target_rate,
        )

        # Open playback stream (kept open, write to it on demand)
        playback_dev_info = sd.query_devices(self._playback_idx, "output")
        playback_native_rate = int(playback_dev_info["default_samplerate"])
        self._playback_stream = sd.OutputStream(
            device=self._playback_idx,
            samplerate=playback_native_rate,
            channels=1,
            dtype="float32",
        )
        self._playback_stream.start()
        logger.info("Audio playback stream opened (rate=%d)", playback_native_rate)

        # Start async consumer that feeds audio to callback
        self._consumer_task = asyncio.create_task(self._consume_audio(on_audio_chunk))

    async def _consume_audio(self, on_audio_chunk: Callable[[bytes], Awaitable[None]]) -> None:
        """Consume audio chunks from the queue and forward to callback."""
        while self._running:
            try:
                pcm_bytes = await asyncio.wait_for(self._audio_queue.get(), timeout=1.0)
                await on_audio_chunk(pcm_bytes)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in audio consumer")

    def play_audio(self, pcm_data: bytes, sample_rate: int) -> None:
        """Play PCM audio data through the playback device.

        Args:
            pcm_data: Raw PCM 16-bit mono audio bytes.
            sample_rate: Sample rate of the input PCM data.
        """
        if self._playback_stream is None or not self._running:
            logger.warning("Playback stream not available")
            return

        try:
            # Convert PCM bytes to float32
            audio = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0

            # Resample to playback device rate
            playback_dev_info = sd.query_devices(self._playback_idx, "output")
            playback_rate = int(playback_dev_info["default_samplerate"])
            audio = _resample(audio, sample_rate, playback_rate)

            # Write to playback stream
            self._playback_stream.write(audio.reshape(-1, 1))
            logger.debug("Played %d samples at %dHz", len(audio), playback_rate)
        except Exception:
            logger.exception("Error playing audio")

    async def stop(self) -> None:
        """Stop capture and playback streams."""
        self._running = False

        if self._consumer_task is not None:
            self._consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._consumer_task
            self._consumer_task = None

        if self._capture_stream is not None:
            try:
                self._capture_stream.stop()
                self._capture_stream.close()
            except Exception:
                logger.debug("Capture stream close error", exc_info=True)
            self._capture_stream = None

        if self._playback_stream is not None:
            try:
                self._playback_stream.stop()
                self._playback_stream.close()
            except Exception:
                logger.debug("Playback stream close error", exc_info=True)
            self._playback_stream = None

        logger.info("Audio bridge stopped")
