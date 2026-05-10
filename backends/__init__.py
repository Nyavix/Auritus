"""
Pluggable inference backends for AriasSTT.

Two backends are exposed:

* ``FasterWhisperBackend`` -- the original CPU path via faster-whisper /
  CTranslate2.  Always available; the CTranslate2 wheels ship with their
  own kernels, so no GPU runtime is required.
* ``WhisperCppBackend`` -- shells out to a bundled ``whisper-server.exe``
  built with ``-DGGML_VULKAN=1``.  Vendor-agnostic GPU acceleration via
  Vulkan (works on AMD, NVIDIA, and Intel GPUs).  Available only when the
  Vulkan-built ``whisper-server`` binary is bundled with the install.

The backends share a tiny abstract surface (``load`` / ``transcribe`` /
``unload``) so the tray app can swap between them at runtime without
caring about format differences (CTranslate2 vs GGUF, in-process vs
subprocess).

Audio in / text out is the contract.  Everything else is the backend's
problem.
"""

from .base import Backend
from .faster_whisper_backend import FasterWhisperBackend
from .whisper_cpp_backend import WhisperCppBackend

__all__ = ["Backend", "FasterWhisperBackend", "WhisperCppBackend"]
