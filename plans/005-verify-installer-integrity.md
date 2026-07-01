# Plan 005: The auto-updater refuses to run an installer whose bytes don't match the SHA256 published in its GitHub release

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 10b48d1..HEAD -- dictate.py .github/workflows/release.yml`
> If either changed since this plan was written, compare the "Current state"
> excerpts against the live code before proceeding; on a mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: 001 (adds a test to `tests/test_dictate_helpers.py`)
- **Category**: security (integrity)
- **Planned at**: commit `10b48d1`, 2026-07-01

## Why this matters

On launch, Auritus polls GitHub Releases; if a newer version exists, the tray
offers "Install update", which downloads the installer `.exe` and runs it
**silently** (`/SILENT /SUPPRESSMSGBOXES /CLOSEAPPLICATIONS`) with **no integrity
check of any kind**. The only guarantee today is TLS + GitHub's trust; a
corrupted/truncated download, a poisoned CDN response, or a tampered asset is
executed unattended in the user's session, and the installer's hash is never even
logged, so an anomaly is undetectable after the fact.

**Scope of the guarantee this plan adds (be honest about it):** the release CI
publishes a `.sha256` sidecar next to the installer; the updater fetches it,
verifies the downloaded bytes match before executing, always logs the hash, and
enforces the HTTP `Content-Length`. This defends against **transport corruption,
truncation, and any tampering that doesn't also update the sidecar**. It does
**NOT** defend against a fully compromised GitHub release (an attacker who can
replace the `.exe` can replace the `.sha256` too) — that requires code signing or
a client-baked public key, which the roadmap (`docs/ROADMAP.md`, "Decisions on
record") explicitly defers. This plan deliberately does **not** add Authenticode.

## Current state

`dictate.py`:

```python
# line 269
UPDATE_REPO = "Nyavix/Auritus"
...
_UPDATE_USER_AGENT = f"Auritus/{__version__} (+https://github.com/{UPDATE_REPO})"

# line 289
def check_for_update() -> tuple[str, str] | None:
    url = f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"
    req = urllib.request.Request(url, headers={"User-Agent": _UPDATE_USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=UPDATE_API_TIMEOUT_S) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    tag = data.get("tag_name", "")
    latest = _parse_version(tag)
    current = _parse_version(__version__)
    if latest <= current:
        return None
    for asset in data.get("assets", []) or []:
        name = asset.get("name", "")
        if name.startswith("Auritus-Setup") and name.endswith(".exe"):
            url = asset.get("browser_download_url")
            if url:
                return tag.lstrip("vV"), url
    return None

# line 317
def download_installer(url: str, dest_path: str) -> None:
    """Stream an installer from `url` to `dest_path`."""
    req = urllib.request.Request(url, headers={"User-Agent": _UPDATE_USER_AGENT})
    with urllib.request.urlopen(req, timeout=UPDATE_DOWNLOAD_TIMEOUT_S) as resp, \
         open(dest_path, "wb") as f:
        shutil.copyfileobj(resp, f, length=64 * 1024)
```

```python
# line 1709 (in __init__)
        self._pending_update: tuple[str, str] | None = None  # (version, installer_url)

# line 2121
    def _check_update_worker(self) -> None:
        try:
            result = check_for_update()
        except urllib.error.URLError as e:
            log(f"Update check: network error: {e}")
            return
        except Exception as e:
            log(f"Update check failed: {e}\n{traceback.format_exc()}")
            return
        if result is None:
            log(f"Update check: up to date (current v{__version__}).")
            return
        version, url = result
        self._pending_update = (version, url)
        log(f"Update available: v{version} -> {url}")
        ...

# line 2161
    def _do_install_update(self) -> None:
        assert self._pending_update is not None
        version, url = self._pending_update
        try:
            notify_force(APP_NAME, f"Downloading update v{version}...", timeout=3)
            log(f"Downloading update v{version} from {url}")
            tmp_dir = tempfile.gettempdir()
            installer_path = os.path.join(tmp_dir, f"Auritus-Setup-v{version}.exe")
            download_installer(url, installer_path)
            log(f"Installer downloaded: {installer_path}")
            notify_force(APP_NAME, f"Installing v{version}. App will restart.", timeout=4)
            time.sleep(1.0)
            subprocess.Popen(
                [installer_path, "/SILENT", "/SUPPRESSMSGBOXES", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
                close_fds=True,
            )
            time.sleep(2.0)
        except Exception as e:
            log(f"Update install failed: {e}\n{traceback.format_exc()}")
            notify_error(APP_NAME, f"Update failed: {e}")
        finally:
            self._update_in_flight = False
            ...
```

- `dictate.py` does **not** currently `import hashlib`. Its import block is at
  lines 147-164 (`os, re, io, json, math, time, queue, shutil, socket, struct,
  ctypes, tempfile, threading, traceback, subprocess, urllib.error,
  urllib.request`).
- `.github/workflows/release.yml` — the release pipeline. Relevant tail:

  ```yaml
        - name: Compile installer
          shell: pwsh
          run: |
            $iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
            ...
            & $iscc installer.iss
        - name: List installer output
          shell: pwsh
          run: Get-ChildItem installer-output
        - name: Upload installer to release
          uses: softprops/action-gh-release@v2
          with:
            files: installer-output/Auritus-Setup-v*.exe
            generate_release_notes: true
            fail_on_unmatched_files: true
            token: ${{ secrets.GITHUB_TOKEN }}
  ```

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Tests (needs display) | `xvfb-run -a python3 -m pytest -q` (Linux) | all pass |
| Ruff | `python3 -m ruff check .` | exit 0 |
| YAML sanity | `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml')); print('ok')"` | `ok` |

## Scope

**In scope**:
- `dictate.py` — `import hashlib`; `check_for_update` (return + sidecar fetch);
  `download_installer` (return hash + truncation check); the `_pending_update`
  type; `_check_update_worker`; `_do_install_update` (verify before Popen)
- `.github/workflows/release.yml` — add a SHA256 sidecar step + upload it
- `tests/test_dictate_helpers.py` — add `download_installer` tests
- `plans/README.md` — status update

**Out of scope** (do NOT touch):
- The installer flags / silent-install behavior — unchanged; we gate *whether* we
  run it, not *how*.
- Code signing / Authenticode / `wintrust` — explicitly deferred (roadmap).
- The `_start_update_check` dev-mode skip (`sys.frozen` gate) — unchanged.

## Git workflow

- Branch: `advisor/005-installer-integrity`
- One commit, conventional style: `fix(update): verify installer sha256 (release sidecar) before silent exec`
- Do NOT push or open a PR unless asked.

## Steps

### Step 1: `import hashlib`

Add `import hashlib` to the import block (near `import shutil`).

**Verify**: `grep -n '^import hashlib' dictate.py` → one match.

### Step 2: `download_installer` returns the hash and enforces length

Replace `download_installer` (lines ~317-322):

```python
def download_installer(url: str, dest_path: str) -> str:
    """Stream an installer from `url` to `dest_path`; return its SHA256 hex digest.

    Raises OSError if the download is truncated (bytes written != Content-Length).
    """
    req = urllib.request.Request(url, headers={"User-Agent": _UPDATE_USER_AGENT})
    h = hashlib.sha256()
    written = 0
    with urllib.request.urlopen(req, timeout=UPDATE_DOWNLOAD_TIMEOUT_S) as resp, \
         open(dest_path, "wb") as f:
        clen = resp.headers.get("Content-Length")
        expected_len = int(clen) if clen and clen.isdigit() else None
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            written += len(chunk)
    if expected_len is not None and written != expected_len:
        raise OSError(f"installer download truncated: {written} of {expected_len} bytes")
    return h.hexdigest()
```

**Verify**: `grep -n 'def download_installer' dictate.py` shows `-> str`.

### Step 3: `check_for_update` finds the sidecar and returns the expected hash

Replace the asset loop + return of `check_for_update` so it returns a 3-tuple
`(version, installer_url, expected_sha256_or_None)`:

```python
def check_for_update() -> "tuple[str, str, str | None] | None":
    url = f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _UPDATE_USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=UPDATE_API_TIMEOUT_S) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    tag = data.get("tag_name", "")
    if _parse_version(tag) <= _parse_version(__version__):
        return None

    assets = data.get("assets", []) or []
    installer_url = None
    for asset in assets:
        name = asset.get("name", "")
        if name.startswith("Auritus-Setup") and name.endswith(".exe"):
            installer_url = asset.get("browser_download_url")
            break
    if not installer_url:
        return None

    # Optional integrity sidecar published by CI (Auritus-Setup-*.exe.sha256).
    expected_sha = None
    for asset in assets:
        name = asset.get("name", "")
        if name.startswith("Auritus-Setup") and name.endswith(".exe.sha256"):
            sha_url = asset.get("browser_download_url")
            if sha_url:
                try:
                    sreq = urllib.request.Request(sha_url, headers={"User-Agent": _UPDATE_USER_AGENT})
                    with urllib.request.urlopen(sreq, timeout=UPDATE_API_TIMEOUT_S) as r:
                        # sha256sum format is "<hex>  <filename>"; take the hex.
                        expected_sha = r.read().decode("utf-8", "replace").split()[0].strip() or None
                except Exception as e:
                    log(f"Update: could not fetch installer sha256 sidecar: {e}")
            break

    return tag.lstrip("vV"), installer_url, expected_sha
```

**Verify**: `grep -n 'exe.sha256' dictate.py` → one match.

### Step 4: Thread the 3-tuple through `_pending_update`

- At `dictate.py:1709` change the type comment:
  ```python
          self._pending_update: "tuple[str, str, str | None] | None" = None  # (version, url, sha256)
  ```
- In `_check_update_worker` (line ~2133), replace `version, url = result` /
  `self._pending_update = (version, url)` with:
  ```python
          version, url, _sha = result
          self._pending_update = result
          log(f"Update available: v{version} -> {url}" + ("" if _sha else " (no sha256 sidecar)"))
  ```

**Verify**: `grep -n 'version, url, _sha = result' dictate.py` → one match.

> The only two sites that *unpack* `_pending_update` as a tuple are
> `_check_update_worker` (this step) and `_do_install_update` (Step 5) — both are
> updated to the 3-tuple. Two other sites read it but need **no change**:
> `install_update` only null-checks it (`if self._pending_update is None ...`), and
> `_build_menu`'s tray-label closures (~lines 2669-2678) read `self._pending_update[0]`
> and its truthiness — index access and null-checks work identically on a 3-tuple.
> Do not edit those two.

### Step 5: Verify before executing in `_do_install_update`

Replace the unpack + the block from `download_installer(...)` through the
`subprocess.Popen(...)` call:

```python
        version, url, expected_sha = self._pending_update
        try:
            notify_force(APP_NAME, f"Downloading update v{version}...", timeout=3)
            log(f"Downloading update v{version} from {url}")
            tmp_dir = tempfile.gettempdir()
            installer_path = os.path.join(tmp_dir, f"Auritus-Setup-v{version}.exe")
            actual_sha = download_installer(url, installer_path)
            log(f"Installer downloaded: {installer_path} sha256={actual_sha}")

            if expected_sha:
                if actual_sha.lower() != expected_sha.lower():
                    log(f"Installer sha256 MISMATCH: expected {expected_sha}, got {actual_sha}; aborting.")
                    notify_error(APP_NAME, "Update aborted: installer failed its integrity check.")
                    try:
                        os.remove(installer_path)
                    except OSError:
                        pass
                    return
                log("Installer sha256 verified against release sidecar.")
            else:
                log("No sha256 sidecar published for this release; proceeding (hash logged above).")

            notify_force(APP_NAME, f"Installing v{version}. App will restart.", timeout=4)
            time.sleep(1.0)
            # /SILENT shows progress without prompts; /SUPPRESSMSGBOXES auto-OKs
            # any dialogs; /CLOSEAPPLICATIONS lets installer kill us;
            # /RESTARTAPPLICATIONS relaunches the new exe after install.
            subprocess.Popen(
                [installer_path, "/SILENT", "/SUPPRESSMSGBOXES", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
                close_fds=True,
            )
            # Don't quit ourselves -- the installer's CloseApplications handler
            # will close us cleanly. Sleep a moment to give it the handle.
            time.sleep(2.0)
```

Leave the surrounding `except`/`finally` intact. The two comments above
(`/SILENT ...` and `Don't quit ourselves ...`) exist in the original code — keep
them; do not let a mechanical replace delete them.

**Verify**: `grep -n 'Installer sha256 verified' dictate.py` → one match; the
`return` on mismatch is present.

### Step 6: Publish the sidecar from CI

In `.github/workflows/release.yml`, add a step **after** "Compile installer" and
**before** "Upload installer to release" (there is an existing "List installer
output" step between those two — placing the new step either just before or just
after it is fine; it only affects the debug listing):

```yaml
      - name: Compute installer SHA256 sidecar
        shell: pwsh
        run: |
          $exe = Get-ChildItem installer-output/Auritus-Setup-v*.exe | Select-Object -First 1
          if (-not $exe) { Write-Error "installer .exe not found"; exit 1 }
          $hash = (Get-FileHash $exe.FullName -Algorithm SHA256).Hash.ToLower()
          "$hash  $($exe.Name)" | Set-Content -NoNewline -Encoding ascii "$($exe.FullName).sha256"
          Write-Host "sha256($($exe.Name)) = $hash"
```

And change the upload step's `files:` to include the sidecar:

```yaml
      - name: Upload installer to release
        uses: softprops/action-gh-release@v2
        with:
          files: |
            installer-output/Auritus-Setup-v*.exe
            installer-output/Auritus-Setup-v*.exe.sha256
          generate_release_notes: true
          fail_on_unmatched_files: true
          token: ${{ secrets.GITHUB_TOKEN }}
```

**Verify**: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml')); print('ok')"` → `ok`; `grep -n 'sha256' .github/workflows/release.yml` shows both new lines.

### Step 7: Add tests for `download_installer`

Append to `tests/test_dictate_helpers.py`:

```python
class _FakeHttpResp:
    def __init__(self, body, content_length):
        import io
        self._buf = io.BytesIO(body)
        self.headers = {"Content-Length": content_length} if content_length is not None else {}
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self, n=-1): return self._buf.read(n)


def test_download_installer_returns_sha256(dictate, tmp_path, monkeypatch):
    import hashlib
    body = b"pretend installer bytes" * 100
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: _FakeHttpResp(body, str(len(body))),
    )
    dest = tmp_path / "Setup.exe"
    digest = dictate.download_installer("https://example/Setup.exe", str(dest))
    assert digest == hashlib.sha256(body).hexdigest()
    assert dest.read_bytes() == body


def test_download_installer_rejects_truncated(dictate, tmp_path, monkeypatch):
    import pytest
    body = b"short"
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: _FakeHttpResp(body, "9999"),  # lies about length
    )
    dest = tmp_path / "Setup.exe"
    with pytest.raises(OSError):
        dictate.download_installer("https://example/Setup.exe", str(dest))
```

**Verify**: `xvfb-run -a python3 -m pytest -q tests/test_dictate_helpers.py -k download_installer` → both pass.

### Step 8: Update the plan index

Set this plan's row in `plans/README.md` to `DONE`.

## Test plan

- New tests: `download_installer` returns the correct SHA256 and raises on a
  truncated (length-mismatched) download.
- The mismatch-abort decision in `_do_install_update` is not unit-tested (it ends
  in `subprocess.Popen`); it is covered by reading + the manual release loop.
- Manual verification (requires a real tagged release with the sidecar): after
  this ships and one release is cut, a tester's client should log
  `Installer sha256 verified against release sidecar.` before installing.
- Verification: `xvfb-run -a python3 -m pytest -q` → all pass.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n '^import hashlib' dictate.py` → one match
- [ ] `grep -n 'exe.sha256' dictate.py` and `grep -n 'Installer sha256 verified' dictate.py` → one match each
- [ ] `grep -n 'version, url, _sha = result' dictate.py` → one match (3-tuple threaded)
- [ ] `.github/workflows/release.yml` has the sidecar step and uploads the `.sha256`; file is valid YAML
- [ ] `xvfb-run -a python3 -m pytest -q` exits 0 with the 2 new tests passing
- [ ] `python3 -m ruff check .` exits 0
- [ ] Only in-scope files modified (`git status`)
- [ ] `plans/README.md` row for 005 says DONE

## STOP conditions

Stop and report back if:

- `check_for_update` / `_do_install_update` / `download_installer` don't match the
  "Current state" excerpts (drift) — the update flow changed; re-locate or STOP.
- You find a *third* consumer of `_pending_update` beyond `_check_update_worker`,
  `install_update`, and `_do_install_update` that unpacks it as a 2-tuple — update
  it to the 3-tuple too, or STOP if the shape is load-bearing elsewhere.
  (`grep -n "_pending_update" dictate.py` to enumerate all sites before editing.)
- A test needs a real network call — it doesn't; the mock is complete.

## Maintenance notes

- **Guarantee ceiling (put this in the PR description):** the sidecar hash defends
  transport corruption / truncation / partial tamper, NOT a compromised GitHub
  release. Upgrading to real protection means signing the installer and baking a
  public key into the client — a separate, larger change gated on signing infra
  (roadmap-deferred). Don't let this fix create false confidence.
- Every future release now MUST publish the sidecar (CI does it automatically). A
  release cut by hand without the sidecar will still update but log
  "No sha256 sidecar published" — acceptable, but prefer tagging so CI runs.
- If the installer asset naming ever changes (`Auritus-Setup-*.exe`), update both
  the matcher in `check_for_update` and the CI glob together.
- Reviewer should scrutinize: the mismatch path returns *before* `Popen` (no
  execution of a bad file), and the temp file is removed on mismatch.
