"""
Abstract Backend interface.

A backend wraps a Whisper inference engine.  ``DictateApp`` knows nothing
about model formats or process boundaries -- it loads a model, hands the
backend an audio array, and gets back a string.

Backends are *not* thread-safe.  ``DictateApp`` already serialises calls
through its ``_state_lock`` (transcription and model swap can never run
concurrently), and that's the only invariant the implementations rely
on.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

import numpy as np


# Type for the optional logger injected by DictateApp so backend output
# lands in the same ariasstt.log file as the rest of the app.
LogFn = Callable[[str], None]


class Backend(ABC):
    # Stable machine name persisted in config.json (``"cpu"`` / ``"gpu"``).
    name: str = "abstract"

    # Human-readable label shown in the tray menu and tooltip.
    label: str = "Abstract backend"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    @abstractmethod
    def available(cls) -> tuple[bool, str]:
        """Return ``(is_available, reason)``.

        ``is_available=False`` greys the backend out in the tray menu and
        ``reason`` is shown in the tooltip / log so the user understands
        why GPU isn't an option (e.g. binary not bundled, no Vulkan
        device).  Cheap probes only -- this is called on every menu
        rebuild.
        """

    @abstractmethod
    def load(self, model_name: str) -> None:
        """Load (or reload) a model.  Raises on failure."""

    @abstractmethod
    def transcribe(self, audio: np.ndarray) -> str:
        """Run inference on a 16 kHz mono float32 array, return text."""

    @abstractmethod
    def unload(self) -> None:
        """Release the model / kill subprocess.  Idempotent."""

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"
