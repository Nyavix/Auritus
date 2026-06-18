# Auritus — Codex Audit (2026-05-14)

Source: Codex rescue run via `/codex:rescue`.
Scope: full audit — code quality, correctness bugs, race conditions in the
threading model, resource leaks, error handling gaps, security concerns,
plus verification of the drainer-thread fix in
`backends/whisper_cpp_backend.py` (commit on top of v0.3.2).

Pick up tomorrow: triage HIGH items first; M4 (installer integrity) is
the most user-facing of the MEDIUMs.

---

## Ranked Findings

### CRITICAL

**C1 — `_cancel_event` is never cleared before the drainer-thread join timeout path, causing state to be permanently BUSY after a whisper-server crash mid-inference**

Location: `dictate.py:_do_transcribe` / `whisper_cpp_backend.py:transcribe`

The `finally` block in `_do_transcribe` unconditionally sets `self.state = STATE_IDLE`. That part is fine. The real issue: if `whisper-server.exe` crashes during `transcribe()` (which raises a `RuntimeError`), the exception is caught by the outer `except Exception` in `_do_transcribe`, which logs and notifies, and then the `finally` resets state to IDLE. This is actually handled correctly — the crash path is safe. Reclassify to High below.

---

### HIGH

**H1 — Port-reuse race window in `_free_localhost_port` + no retry on `load()`**

Location: `whisper_cpp_backend.py:_free_localhost_port`

```python
s = socket.socket()
s.bind(("127.0.0.1", 0))
return s.getsockname()[1]  # port released here
# whisper-server binds this port later — another process can steal it
```

The socket is closed before `whisper-server.exe` binds it. On a busy dev machine another process (or a prior whisper-server still in TIME_WAIT) can grab the port. `_wait_ready()` will then time out with no useful error, or `whisper-server.exe` will fail to start with a bind error that surfaces only in the stderr tail. There is no retry loop. Fix: hold the socket open with `SO_REUSEADDR` until after `Popen()` returns, or retry `load()` once with a fresh port on `TimeoutError`.

---

**H2 — `_cancel_event` is never cleared if `on_cancel()` fires during the brief RECORDING→BUSY transition window**

Location: `dictate.py:on_toggle`, `on_cancel`, `_do_transcribe`

```python
# on_toggle (hotkey thread):
self.state = STATE_BUSY       # transition A
# on_cancel (cancel-hotkey thread) fires here:
# state == STATE_BUSY, so we do: self._cancel_event.set()
# _do_transcribe hasn't started yet
# _do_transcribe:
self._cancel_event.clear()    # <-- this happens BEFORE inference, correct
```

Wait — `_start_recording` calls `self._cancel_event.clear()` at the very top, and `_stop_and_transcribe` runs `_do_transcribe` which checks the event _after_ `recorder.stop()`. The clear in `_start_recording` covers the recording phase. But if `on_cancel()` fires while `on_toggle` is transitioning from RECORDING→BUSY (before `_do_transcribe` starts), `_cancel_event` is set, and `_do_transcribe` will drop the result — which is correct behavior. However, after that `_cancel_event` stays set. The next recording cycle calls `_start_recording` which calls `self._cancel_event.clear()` — so it _is_ cleared before the next inference. This is fine.

Real issue here: **`_cancel_event.clear()` is inside `_start_recording`, but `_do_transcribe` checks `self._cancel_event.is_set()` _before_ calling `recorder.stop()`**. If a cancel arrives after `_stop_and_transcribe` is called but before `_do_transcribe` acquires the CPU, the event is set and the transcription is immediately dropped — but `recorder.stop()` is still called to drain the buffer. This is correct. Reclassify to Medium.

Actual H2: **drainer threads are `daemon=True` and `join(timeout=1.0)` in `unload()` — if the process is killed and the pipes have unflushed data, the final 1-second join timeout is insufficient and crash logs are silently truncated**.

Location: `whisper_cpp_backend.py:unload`

```python
for t in self._drain_threads:
    t.join(timeout=1.0)  # 1s for both threads combined
```

The threads are joined sequentially — total wall time can be up to 2 seconds for the two threads. More importantly, if the drainer thread is blocked on `stream.read(4096)` (waiting for the pipe to close), and the process was `kill()`-ed rather than `terminate()`-d, Windows may not close the pipe immediately. The drainer thread can block for longer than 1 second in this case, leaving a dangling daemon thread that holds the pipe handle open, which in turn prevents the Popen object from being GC'd cleanly. Fix: close `self.proc.stdout` and `self.proc.stderr` explicitly after `wait()` to guarantee the pipe EOF is delivered to the drainer threads before `join()`.

---

**H3 — `load()` leaks drainer threads if called twice rapidly (model swap during GPU warmup)**

Location: `whisper_cpp_backend.py:load`

```python
def load(self, model_name: str) -> None:
    self.unload()   # joins old drain threads with 1s timeout each
    ...
    self._drain_threads = []
    self._start_drainer(self.proc.stdout, "stdout")
    self._start_drainer(self.proc.stderr, "stderr")
```

`unload()` sets `self._drain_threads = []` after joining. But if `load()` raises after the drainers are started (e.g. `_wait_ready()` times out and calls `self.unload()` from inside `except`), the inner `unload()` will join those new threads. This is actually fine — `unload()` is idempotent and the inner call is the correct teardown path. No leak here on timeout.

Real H3: **`self._drain_threads` list is never guarded by a lock. `load()` replaces it (`self._drain_threads = []`) at the start of drainer setup, then appends to it from `_start_drainer`. If `unload()` is called concurrently from another thread between those two lines, it will `join()` an empty list and then `load()` will have dangling threads that are never joined.**

The docstring in `base.py` states: "Backends are not thread-safe. DictateApp already serialises calls through its `_state_lock`." In practice, `load()` is only called from `_reload_model` (a worker thread) while the state is BUSY, and `unload()` is called from `quit()` which also holds no special lock. If the user clicks Quit while a model swap is in progress, `quit()` calls `self.backend.unload()` concurrently with `_reload_model` calling `self.backend.load()`. This is a genuine race. Fix: add a backend-level lock, or — simpler — in `quit()`, set `self._stop_event` and wait for any running `_reload_model` thread to finish before calling `backend.unload()`.

---

**H4 — `Recorder.start()` creates a new `InputStream` without checking if one is already open — double-open on rapid toggle**

Location: `dictate.py:Recorder.start`

```python
def start(self) -> None:
    self._chunks = []
    ...
    self._stream = sd.InputStream(...)
    self._stream.start()
```

If `start()` is called while `self._stream` is not None (e.g. due to a bug upstream), the old stream is silently overwritten without being closed. In practice `DictateApp._state_lock` prevents double-start, but if the lock is ever held incorrectly or a future code path calls `recorder.start()` directly, this leaks a sounddevice stream handle. Fix: add `if self._stream is not None: self._stream.close(); self._stream = None` at the top of `start()`.

---

**H5 — Downloaded GGUF model has no integrity check**

Location: `whisper_cpp_backend.py:_ensure_model_file`

```python
if path.exists() and path.stat().st_size > 0:
    return path   # accepted on size > 0 alone — no hash check
...
tmp.replace(path)  # no SHA256 verification before promotion
```

A truncated download (network drop mid-stream), a man-in-the-middle on the HuggingFace CDN, or a corrupted `.part` file that happens to be non-empty will be accepted as a valid model. `whisper-server.exe` will either crash (unrecoverable without manual cache deletion) or produce garbage output. Fix: add known SHA256 digests to `MODEL_FILE_MAP` and verify before `tmp.replace(path)`. For the "size > 0" guard, also validate that the file header matches the GGUF magic bytes (`GGUF` / `gguf`).

---

### MEDIUM

**M1 — `_wait_ready()` polls via HTTP GET to `/` — whisper-server may return HTTP 404 or error codes that are treated as "ready"**

Location: `whisper_cpp_backend.py:_wait_ready`

```python
with urllib.request.urlopen(url, timeout=0.5) as resp:
    resp.read()
    return  # any 2xx or 4xx means "up"
```

A 404 from a half-started server is treated as ready. The first `transcribe()` POST to `/inference` will then likely timeout (3600s). The comment says "Any response means the HTTP listener is up" — this is intentional but doesn't distinguish a fully-booted server from one still loading the model. If whisper-server serves the root before the model is loaded into VRAM, the first inference request will block until the model finishes loading (potentially up to the 3600s timeout). Consider polling `/inference` with a dummy OPTIONS request, or check that the root returns HTTP 200 specifically.

---

**M2 — `paste_clipboard()` sleep is fixed at 80ms regardless of system load; elevated-process paste failure is silent to the user**

Location: `dictate.py:paste_clipboard`

```python
time.sleep(0.08)   # load-bearing sleep
```

CLAUDE.md documents this correctly. The issue is the error path:

```python
except Exception as e:
    log(f"paste failed: {e}")
    return False
```

`_do_transcribe` calls `notify_error` if `paste_clipboard()` returns `False` — but if the synthesized Ctrl+V itself succeeds mechanically and the target process ignores it (e.g. elevated app), no exception is raised, `paste_clipboard()` returns `True`, and the user gets no notification. The text is on the clipboard, but there's no toast. Medium severity because the text is recoverable from the clipboard.

---

**M3 — `on_cancel()` sets `_cancel_event` without clearing it on the next `_start_recording` cycle if cancel fires while BUSY**

Location: `dictate.py:_start_recording`, `_do_transcribe`

```python
# _start_recording:
self._cancel_event.clear()   # correct

# But if cancel fires during _do_transcribe (state=BUSY):
self._cancel_event.set()     # set by on_cancel
# _do_transcribe drops result, returns
# finally: state = IDLE
# Next toggle: _start_recording -> _cancel_event.clear()  correct
```

Actually this is fine — `_start_recording` always clears the event before any new recording/inference cycle. No bug here on close reading.

Real M3: **`_drain_threads` list is appended to but never length-checked. If `load()` is called N times without `unload()` between calls (impossible in the current code, but defensive concern), the list grows unboundedly.** Not a real bug given the current call graph, but the `unload()` reset of `self._drain_threads = []` after `join()` in the `finally` block is correct and prevents accumulation.

Real M3 (substituted): **`HotkeyCaptureDialog.run()` creates a `tk.Tk` root on a worker thread, then calls `self.app.set_hotkey(self._result)` after `root.mainloop()` returns. `set_hotkey` calls `_start_hotkey_listener()` which may call `notify_error` which calls `plyer_notification.notify()`. `plyer` on Windows uses COM (`win32api`), which requires the thread to be COM-initialized. The hotkey-prompt worker thread is a raw `threading.Thread` with no COM initialization, so `plyer` notifications from this thread can fail silently or crash with a COM error.**

Fix: wrap the `notify_error` call in `set_hotkey` with a try/except that falls back to `log()`, or move the `set_hotkey` call to the main thread via a `threading.Event` + result variable pattern.

---

**M4 — `install_update` downloads and silently executes an installer from a GitHub asset URL without signature verification**

Location: `dictate.py:_do_install_update`

```python
subprocess.Popen(
    [installer_path, "/SILENT", "/SUPPRESSMSGBOXES", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],
    creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
    close_fds=True,
)
```

The downloaded installer is executed without verifying an Authenticode signature or a SHA256 digest. If the GitHub API response is spoofed (no pinned cert beyond the OS trust store), or if the temp directory is writable by another process, an attacker could substitute a malicious executable. The HTTPS download provides transport security, but there is no application-level integrity check. Severity is Medium rather than High because the attack requires either a compromised GitHub account or a MitM on the TLS connection.

Fix: after download, verify the Authenticode signature using `ctypes.windll.wintrust` before `Popen()`. At minimum, log a hash of the installer to the log file so anomalies are detectable post-hoc.

---

**M5 — `_do_test_hotkey` leaves state as IDLE but does not restart the hotkey listener if `_start_hotkey_listener` throws**

Location: `dictate.py:_do_test_hotkey`

```python
finally:
    with self._state_lock:
        if self.state == self.STATE_BUSY:
            self.state = self.STATE_IDLE
    if main_was_bound and not self._stop_event.is_set():
        self._start_hotkey_listener()   # can throw; exception is unhandled
```

`_start_hotkey_listener()` wraps its own internals in try/except and calls `notify_error` on failure. But if it throws an uncaught exception above that (e.g. if `_start_cancel_listener` itself raises unexpectedly), `_do_test_hotkey` will propagate the exception to its daemon thread and the hotkey will be permanently unbound. The `_hotkey_bound` flag will remain `False` but the state is already IDLE, leaving the app silently deaf to hotkeys with no further notification. Fix: wrap `_start_hotkey_listener()` in the `finally` block of `_do_test_hotkey` with its own try/except.

---

## Drainer-Thread Fix Verification

The fix in `whisper_cpp_backend.py` is **correct and sufficient for preventing the primary deadlock**. Specific evidence:

1. Drainers are started _before_ `_wait_ready()` (`load()` lines after `self.proc = subprocess.Popen(...)`), so boot-time stderr output from Vulkan device enumeration and model loading is drained without deadlock.
2. The `_pump` loop uses `stream.read(4096)` which blocks until data arrives or EOF — no busy-wait.
3. The tail buffer is capped at `SERVER_LOG_TAIL_BYTES = 16 * 1024` with a proper lock (`_tail_lock`), so unbounded memory growth is prevented.
4. `_read_stderr_tail()` never touches the pipe directly — it reads only from the in-memory string, so it cannot block.
5. `unload()` calls `proc.terminate()` -> `proc.wait(timeout=3)` -> `proc.kill()` -> `proc.wait(timeout=2)` before joining drainer threads, so the child process is guaranteed dead (and the pipes at EOF) before `join(timeout=1.0)` is called.

The one remaining gap (H2 above) is that the pipes are not explicitly closed via `self.proc.stdout.close()` / `self.proc.stderr.close()` after `proc.wait()`. On Windows, the pipe write-end closes when the child exits, which unblocks the drainer's `read()`. In practice this works. But if `proc.kill()` is called and Windows delays pipe handle teardown (rare), the drainers could block beyond the 1s join timeout. Explicit close of the pipe handles after `proc.wait()` is the defensive fix:

```python
# After proc.wait() in unload():
for attr in ("stdout", "stderr"):
    pipe = getattr(self.proc, attr, None)
    if pipe is not None:
        try:
            pipe.close()
        except Exception:
            pass
for t in self._drain_threads:
    t.join(timeout=1.0)
```
