"""Unit tests for the pure, I/O-free parts of the inference backends.
These need only numpy/scipy/faster-whisper on the path — no display, no audio,
no GTK — so they run on a bare CI runner."""
import io

from backends.whisper_cpp_backend import (
    MODEL_FILE_MAP,
    WhisperCppBackend,
    _build_multipart,
)

EXPECTED_MODELS = ["tiny.en", "base.en", "small.en", "medium.en", "large-v3"]


def test_model_file_map_covers_every_option():
    assert set(MODEL_FILE_MAP) == set(EXPECTED_MODELS)
    for fname in MODEL_FILE_MAP.values():
        assert fname.startswith("ggml-") and fname.endswith(".bin")


def test_build_multipart_shape():
    wav = b"RIFFfake"
    body, content_type = _build_multipart(wav, language="en")
    assert content_type.startswith("multipart/form-data; boundary=")
    boundary = content_type.split("boundary=", 1)[1]
    assert boundary.encode() in body
    assert wav in body
    assert b'name="file"' in body
    assert b'name="language"' in body
    assert body.rstrip().endswith(b"--" + boundary.encode() + b"--")


def test_ensure_model_file_short_circuits_on_existing_file(tmp_path, monkeypatch):
    monkeypatch.setattr("backends.whisper_cpp_backend._models_dir", lambda: tmp_path)
    fname = MODEL_FILE_MAP["tiny.en"]
    (tmp_path / fname).write_bytes(b"not empty")

    def _boom(*a, **k):
        raise AssertionError("network was hit despite a cached model file")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    backend = WhisperCppBackend(log=lambda _m: None)
    result = backend._ensure_model_file("tiny.en")
    assert result == tmp_path / fname


def test_ensure_model_file_rejects_unknown_model(tmp_path, monkeypatch):
    monkeypatch.setattr("backends.whisper_cpp_backend._models_dir", lambda: tmp_path)
    backend = WhisperCppBackend(log=lambda _m: None)
    try:
        backend._ensure_model_file("does-not-exist")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unknown model")


class _FakeResp:
    """Minimal stand-in for the urlopen response context manager."""
    def __init__(self, body: bytes, content_length):
        self._buf = io.BytesIO(body)
        self.headers = {"Content-Length": content_length} if content_length is not None else {}
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def read(self, n=-1):
        return self._buf.read(n)


def _install_fake_urlopen(monkeypatch, body, content_length):
    def _fake(url, timeout=None):
        return _FakeResp(body, content_length)
    monkeypatch.setattr("urllib.request.urlopen", _fake)


def test_ensure_model_file_rejects_truncated_download(tmp_path, monkeypatch):
    monkeypatch.setattr("backends.whisper_cpp_backend._models_dir", lambda: tmp_path)
    _install_fake_urlopen(monkeypatch, body=b"0123456789", content_length="100")
    backend = WhisperCppBackend(log=lambda _m: None)
    import pytest
    with pytest.raises(OSError):
        backend._ensure_model_file("tiny.en")
    fname = MODEL_FILE_MAP["tiny.en"]
    assert not (tmp_path / fname).exists()
    assert not (tmp_path / (fname + ".part")).exists()


def test_ensure_model_file_accepts_complete_download(tmp_path, monkeypatch):
    monkeypatch.setattr("backends.whisper_cpp_backend._models_dir", lambda: tmp_path)
    body = b"x" * 64
    _install_fake_urlopen(monkeypatch, body=body, content_length=str(len(body)))
    backend = WhisperCppBackend(log=lambda _m: None)
    result = backend._ensure_model_file("tiny.en")
    assert result.read_bytes() == body


def test_ensure_model_file_rejects_bad_digest(tmp_path, monkeypatch):
    monkeypatch.setattr("backends.whisper_cpp_backend._models_dir", lambda: tmp_path)
    import backends.whisper_cpp_backend as wc
    fname = MODEL_FILE_MAP["tiny.en"]
    monkeypatch.setitem(wc.MODEL_SHA256, fname, "0" * 64)
    body = b"y" * 32
    _install_fake_urlopen(monkeypatch, body=body, content_length=str(len(body)))
    backend = WhisperCppBackend(log=lambda _m: None)
    import pytest
    with pytest.raises(OSError):
        backend._ensure_model_file("tiny.en")
    assert not (tmp_path / fname).exists()
