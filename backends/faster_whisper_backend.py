"""
faster-whisper / CTranslate2 backend (CPU).

This is the original AriasSTT inference path.  Behaviour is identical to
what ``DictateApp._transcribe`` did before the backend split: int8 on
CPU, beam_size=1, VAD filter on, no timestamps, no prior context.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from faster_whisper import WhisperModel

from .base import Backend, LogFn


class FasterWhisperBackend(Backend):
    name = "cpu"
    label = "CPU (faster-whisper)"

    def __init__(self, compute_type: str = "int8", cpu_threads: int = 0,
                 log: LogFn | None = None) -> None:
        self.compute_type = compute_type
        self.cpu_threads = cpu_threads
        self._log = log or (lambda _msg: None)

        self.model: WhisperModel | None = None
        self.model_name: str | None = None

    # ------------------------------------------------------------------

    @classmethod
    def available(cls) -> tuple[bool, str]:
        # CTranslate2 ships its own CPU kernels in the wheel.  Always on.
        return True, ""

    def load(self, model_name: str) -> None:
        self._log(f"[backend:cpu] Loading {model_name} ({self.compute_type})")
        kwargs: dict[str, Any] = dict(device="cpu", compute_type=self.compute_type)
        if self.cpu_threads > 0:
            kwargs["cpu_threads"] = self.cpu_threads
        self.model = WhisperModel(model_name, **kwargs)
        self.model_name = model_name
        self._log(f"[backend:cpu] {model_name} loaded")

    def transcribe(self, audio: np.ndarray) -> str:
        if self.model is None:
            raise RuntimeError("FasterWhisperBackend.transcribe called before load()")
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        # Quiet audio is handled internally by VAD; no normalisation pass.
        segments, _info = self.model.transcribe(
            audio,
            language="en" if self.model_name and self.model_name.endswith(".en") else None,
            beam_size=1,
            vad_filter=True,
            without_timestamps=True,
            condition_on_previous_text=False,
        )
        return " ".join(seg.text for seg in segments)

    def unload(self) -> None:
        # CTranslate2 holds its own thread pool; dropping the reference
        # is enough for the GC to release native memory at the next cycle.
        self.model = None
        self.model_name = None
