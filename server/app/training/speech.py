"""Optional speech recognition for training calls (server side, local – no cloud service).

``faster-whisper`` is *not* a default dependency (model download ≈ 0.5–3 GB, CPU heavy). Install
it on the server with ``uv sync --extra speech`` (or ``pip install faster-whisper``); the model is
loaded lazily on the first request. Without it the endpoint answers 501 with an explanation and
the client falls back to typed input. Text-to-speech runs in the client (voices of the operating
system via the Web Speech API) – no audio leaves the workstation for that.
"""

from __future__ import annotations

import asyncio
import importlib.util
import io
from typing import Any, Protocol

MAX_AUDIO_BYTES = 5 * 1024 * 1024  # ≈ 60 s Opus


class SpeechUnavailableError(Exception):
    pass


class SpeechToText(Protocol):
    name: str

    async def transcribe(self, audio: bytes) -> str: ...


def whisper_installed() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


class WhisperSpeechToText:
    name = "faster-whisper"

    def __init__(self, model: str, device: str) -> None:
        self.model_name = model
        self.device = device
        self._model: Any = None
        self._lock = asyncio.Lock()

    async def _load(self) -> Any:
        async with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel  # optional dependency

                self._model = await asyncio.to_thread(
                    WhisperModel, self.model_name, device=self.device, compute_type="int8"
                )
        return self._model

    async def transcribe(self, audio: bytes) -> str:
        model = await self._load()

        def run() -> str:
            segments, _info = model.transcribe(io.BytesIO(audio), language="de", vad_filter=True)
            return " ".join(s.text.strip() for s in segments).strip()

        return await asyncio.to_thread(run)


def create_stt(model: str, device: str) -> SpeechToText | None:
    return WhisperSpeechToText(model, device) if whisper_installed() else None
