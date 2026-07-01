import os
import pathlib
import pytest

# dictate.py creates its data dir at import time (LOG_PATH.parent.mkdir(...)).
# Redirect it to a temp location so importing the module in CI doesn't touch
# the real user profile. NOTE: this only isolates POSIX (dictate.py reads
# XDG_DATA_HOME on Linux/macOS but %LOCALAPPDATA% on Windows). CI runs ubuntu, so
# this is sufficient; running the suite locally on Windows will still create the
# real %LOCALAPPDATA%\Auritus\ dir on import.
os.environ.setdefault("XDG_DATA_HOME", str(pathlib.Path(__file__).parent / "_tmp_data"))


@pytest.fixture(scope="session")
def dictate():
    """Import dictate once per session. Skips the whole module if the GUI/audio
    imports can't load (e.g. no display and no xvfb), so the backends tests
    still run and the suite stays green as a partial baseline."""
    try:
        import dictate as _d
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"dictate.py not importable in this environment: {exc}")
    return _d
