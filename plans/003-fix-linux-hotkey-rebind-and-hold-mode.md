# Plan 003: Re-selecting a hotkey/mode on Linux no longer spawns a runaway thread, and Hold mode is not offered where it does nothing

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 10b48d1..HEAD -- dictate.py`
> If `dictate.py` changed since this plan was written, compare the "Current state"
> excerpts against the live code before proceeding; on a mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 001 (uses the `tests/` harness + `dictate` fixture)
- **Category**: bug (concurrency + platform UX)
- **Planned at**: commit `10b48d1`, 2026-07-01

## Why this matters

Two bugs, one code path, on the newly-shipped Linux/Wayland platform:

1. **Runaway thread (the serious one).** On Linux the "hotkey listener" is a Unix
   socket listener running in a background `_serve` thread. When the user picks a
   different **Mode** or **Hotkey** from the tray after startup,
   `_start_hotkey_listener` → `_start_socket_listener` closes the old socket and
   starts a *new* `_serve` thread — but the *old* thread's loop only exits on
   `self._stop_event`, which is set only at quit. The old thread keeps calling
   `accept()` on a now-closed file descriptor, which raises immediately (not a
   timeout), is caught, logged, and retried with no sleep — a tight infinite loop
   that **pegs a CPU core and floods `auritus.log` until the app quits.**

2. **Dead Hold mode.** On Linux `_start_hotkey_listener` returns right after
   starting the socket and never builds the hold-chord listener, so the tray's
   "Mode → Hold" does nothing — yet the Mode submenu is still shown and writable
   on Linux, giving silent, misleading UI (and, pre-fix, triggering bug #1).

## Current state

- `dictate.py:1858` — `_start_hotkey_listener` returns early on Linux:

  ```python
  def _start_hotkey_listener(self) -> None:
      if self._hotkey_listener is not None:
          try:
              self._hotkey_listener.stop()
          except Exception as e:
              log(f"Stop old hotkey listener failed: {e}")
          self._hotkey_listener = None
      if not IS_WINDOWS:
          # On Linux the compositor (e.g. niri) owns the keybind.
          self._start_socket_listener()
          return
      ...   # Windows GlobalHotKeys / hold listener below
  ```

- `dictate.py:1959` — `_start_socket_listener`, with the buggy `_serve` loop:

  ```python
  def _start_socket_listener(self) -> None:
      if self._socket_server is not None:
          try:
              self._socket_server.close()
          except Exception:
              pass
          self._socket_server = None
      sock_path = self._socket_path()
      try:
          os.unlink(sock_path)
      except FileNotFoundError:
          pass
      srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
      try:
          srv.bind(sock_path)
          srv.listen(5)
      except Exception as e:
          srv.close()
          self._hotkey_bound = False
          self._hotkey_last_error = str(e)
          log(f"Socket listener failed to bind {sock_path}: {e}")
          notify_error(APP_NAME, f"Socket bind failed: {e}")
          self._refresh_tooltip()
          return
      self._socket_server = srv
      self._hotkey_bound = True
      self._hotkey_last_error = None
      log(f"Socket listener bound: {sock_path}")
      self._refresh_tooltip()

      def _serve() -> None:
          srv.settimeout(0.5)
          while not self._stop_event.is_set():
              try:
                  try:
                      conn, _ = srv.accept()
                  except socket.timeout:
                      continue
                  with conn:
                      cmd = conn.recv(64).decode("utf-8", "replace").strip()
                      log(f"Socket command: {cmd!r}")
                      if cmd == "toggle":
                          self.on_toggle()
                      elif cmd == "cancel":
                          self.on_cancel()
                      elif cmd == "quit":
                          self.quit()
                      elif cmd == "status":
                          conn.sendall(self.state.encode("utf-8"))
              except Exception as e:
                  if not self._stop_event.is_set():
                      log(f"Socket server error: {e}")

      self._socket_thread = threading.Thread(
          target=_serve, daemon=True, name="socket-ipc"
      )
      self._socket_thread.start()
  ```

- `dictate.py:2023` — `set_mode` (reachable from the tray on Linux today):

  ```python
  def set_mode(self, mode: str) -> None:
      """Tray callback: switch between toggle and hold modes."""
      if mode == self.current_mode:
          return
      if mode not in ("toggle", "hold"):
          notify_error(APP_NAME, f"Unknown mode: {mode}")
          return
      ...
  ```

- `dictate.py:2654` — `_build_menu` adds the Mode submenu unconditionally:

  ```python
      pystray.MenuItem("Mode", self._mode_submenu()),
  ```

- `IS_WINDOWS` is defined at `dictate.py:12` (`sys.platform.startswith("win")`).
  `pystray.MenuItem` supports a `visible=` keyword (see the update item at
  `dictate.py:2678`, which uses `visible=lambda item: ...`).

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Tests (needs display) | `xvfb-run -a python3 -m pytest -q` (Linux) | all pass |
| Ruff | `python3 -m ruff check .` | exit 0 |

## Scope

**In scope**:
- `dictate.py` — the `_serve` loop (bug #1), `_build_menu` Mode item + `set_mode`
  guard (bug #2)
- `tests/test_dictate_helpers.py` — add the rebind test
- `plans/README.md` — status update

**Out of scope** (do NOT touch):
- The Windows hotkey path in `_start_hotkey_listener` (GlobalHotKeys / hold
  listener) — Hold mode works on Windows and must keep working.
- The `Hotkey` submenu and `set_hotkey` — changing the hotkey on Linux is a
  separate UX nit (the compositor owns the real keybind); after this fix the
  socket rebind it triggers is harmless. Note it in your report if you like, but
  don't change it here.
- The `ariasstt-toggle` shell script and the socket *protocol* — unchanged.

## Git workflow

- Branch: `advisor/003-linux-hotkey-rebind`
- One commit, conventional style: `fix(linux): stop orphaning the socket-IPC thread on rebind; hide dead Hold mode`
- Do NOT push or open a PR unless asked.

## Steps

### Step 1: Make the old `_serve` loop exit when its socket is replaced or closed

In `_start_socket_listener`, change the `_serve` loop so this generation stops
when `self._socket_server` is no longer the `srv` it owns, and so a closed-socket
error breaks instead of busy-looping. Replace the `_serve` function body with:

```python
      def _serve() -> None:
          srv.settimeout(0.5)
          while not self._stop_event.is_set():
              # A rebind (set_mode / set_hotkey) or quit() replaces/closes
              # self._socket_server. When that happens, THIS generation of the
              # loop must exit instead of spinning on a dead fd.
              if self._socket_server is not srv:
                  break
              try:
                  try:
                      conn, _ = srv.accept()
                  except socket.timeout:
                      continue
                  except OSError:
                      # Socket closed underneath us (rebind/quit) -> exit.
                      break
                  with conn:
                      cmd = conn.recv(64).decode("utf-8", "replace").strip()
                      log(f"Socket command: {cmd!r}")
                      if cmd == "toggle":
                          self.on_toggle()
                      elif cmd == "cancel":
                          self.on_cancel()
                      elif cmd == "quit":
                          self.quit()
                      elif cmd == "status":
                          conn.sendall(self.state.encode("utf-8"))
              except Exception as e:
                  if not self._stop_event.is_set():
                      log(f"Socket server error: {e}")
```

The two changes are: the `if self._socket_server is not srv: break` guard at the
top of the loop, and the `except OSError: break` on `accept()`.

**Verify**: `grep -n 'self._socket_server is not srv' dictate.py` → one match.

### Step 2: Hide the Mode submenu on Linux

In `_build_menu`, change the Mode item (`dictate.py:2654`) to:

```python
            pystray.MenuItem("Mode", self._mode_submenu(), visible=lambda item: IS_WINDOWS),
```

**Verify**: `grep -n '"Mode", self._mode_submenu' dictate.py` shows the `visible=` kwarg.

### Step 3: Guard `set_mode` on Linux (belt-and-suspenders)

At the top of `set_mode` (`dictate.py:2023`), right after the docstring and before
`if mode == self.current_mode:`, add:

```python
        if not IS_WINDOWS:
            # Hold mode needs a key-down/key-up listener the app doesn't own on
            # Wayland (the compositor sends a single "toggle"). Don't pretend.
            notify(APP_NAME, "Hold mode is Windows-only; Linux uses the compositor keybind.")
            return
```

**Verify**: `grep -n 'Hold mode is Windows-only' dictate.py` → one match.

### Step 4: Add a regression test for the runaway thread

In `tests/test_dictate_helpers.py`, add:

```python
def test_socket_listener_old_thread_exits_on_rebind(dictate, tmp_path, monkeypatch):
    """BUG-01: rebinding the Linux socket listener must not leave the previous
    _serve thread spinning on a closed fd. Build a minimal app object (skip the
    heavy __init__, which pulls GTK/audio) and exercise the real methods."""
    import threading
    import time

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    app = object.__new__(dictate.DictateApp)  # bypass __init__
    app._socket_server = None
    app._socket_thread = None
    app._stop_event = threading.Event()
    app._hotkey_bound = False
    app._hotkey_last_error = None
    app.state = "idle"
    app._refresh_tooltip = lambda: None
    app.on_toggle = lambda: None
    app.on_cancel = lambda: None
    app.quit = lambda: None

    try:
        app._start_socket_listener()
        first = app._socket_thread
        assert first is not None and first.is_alive()

        app._start_socket_listener()  # rebind -> old thread must exit
        # Old loop wakes at most every 0.5s; give it margin.
        deadline = time.time() + 3.0
        while first.is_alive() and time.time() < deadline:
            time.sleep(0.1)
        assert not first.is_alive(), "old _serve thread kept running after rebind"
    finally:
        app._stop_event.set()
        if app._socket_server is not None:
            app._socket_server.close()
```

> This test is Linux/POSIX-oriented (AF_UNIX). On Windows it will skip via the
> `dictate` fixture only if `dictate` itself fails to import; if it imports but
> AF_UNIX is unavailable, guard by adding at the top of the test:
> `import socket; ` then `if not hasattr(socket, "AF_UNIX"): pytest.skip("no AF_UNIX")`
> (import `pytest` at module top — plan 001 already does).

**Verify**: `xvfb-run -a python3 -m pytest -q tests/test_dictate_helpers.py::test_socket_listener_old_thread_exits_on_rebind`
→ passes. Run it against the UNPATCHED loop first if you want to see it fail
(optional): revert Step 1, run — the assertion should fail (old thread alive) —
then re-apply Step 1.

### Step 5: Update the plan index

Set this plan's row in `plans/README.md` to `DONE`.

## Test plan

- New test `test_socket_listener_old_thread_exits_on_rebind` — proves the old
  `_serve` thread terminates after a rebind (the core of BUG-01).
- No new automated test for the Mode-submenu visibility (pystray menu rendering
  isn't unit-testable headlessly); verify manually per below.
- Manual verification (Linux, if a machine is available): run `python dictate.py`,
  right-click tray → confirm **no Mode entry**; pick a different Hotkey preset,
  then `top`/`htop` shows no runaway python thread and `auritus.log` is not
  flooding. This is the manual loop the repo already uses (CLAUDE.md).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n 'self._socket_server is not srv' dictate.py` → one match
- [ ] `grep -n 'except OSError' dictate.py` shows the new break in `_serve`
- [ ] `grep -n 'visible=lambda item: IS_WINDOWS' dictate.py` → at least one match (the Mode item)
- [ ] `grep -n 'Hold mode is Windows-only' dictate.py` → one match
- [ ] `xvfb-run -a python3 -m pytest -q` exits 0, including the new rebind test
- [ ] `python3 -m ruff check .` exits 0
- [ ] Only in-scope files modified (`git status`)
- [ ] `plans/README.md` row for 003 says DONE

## STOP conditions

Stop and report back if:

- `_start_socket_listener` / `_serve` don't match the "Current state" excerpt
  (drift) — the fix location moved; re-locate or STOP.
- The new test passes even against the UNPATCHED loop (Step 4 optional check) —
  that means the environment isn't reproducing the bug; report it, keep the fix.
- Constructing `object.__new__(dictate.DictateApp)` and calling
  `_start_socket_listener` raises for a reason other than a missing attribute you
  can set in the test setup — STOP and report (the method may depend on more
  state than listed).

## Maintenance notes

- If a future change makes `set_hotkey`/`set_mode` do real work on Linux, the
  `_serve` rebind guard still holds — it keys on socket identity, not the caller.
- If Hold mode is ever supported on Wayland (e.g. via a richer `ariasstt-toggle`
  press/release protocol), reverse Steps 2–3 and add the real listener.
- Reviewer should confirm the Windows path in `_start_hotkey_listener` is
  untouched and Hold mode still works on Windows.
