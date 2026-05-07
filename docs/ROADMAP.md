# Roadmap

Living doc. Pick this up at the start of every session — it's the
fastest way to remember where we are and what's next.

---

## Where we are

| Released | Tag | Highlights |
|---|---|---|
| ✅ | `v0.1.0` | First public source release. Tray app, hotkey rebind menu. |
| ✅ | `v0.2.0` | Live waveform glass overlay, hotkey reliability suite (P0–P5), Codex/Gemini review fixes (P6–P8), first installable Inno Setup `.exe`. |
| ✅ | `v0.2.1` | In-app auto-update via GitHub Releases polling. GitHub Actions release pipeline (tag → build → upload, hands-off). |

**Repo:** https://github.com/Nyavix/AriasSTT
**Latest installer:** https://github.com/Nyavix/AriasSTT/releases/latest

**Testers** (Windows, as of v0.2.0):
- Sister
- Friend #1

Mac friend deferred until v0.4.0.

**Auto-update is live.** Tags pushed from now on land on tester machines
automatically within 30 s of their next launch. Manual reinstall is no
longer the loop.

---

## Up next: v0.3.0 — Settings GUI + first-run wizard

Driven by what testers actually struggle with. Don't start until they've
spent at least a few days with v0.2.1.

### Backlog

- [ ] **Settings GUI window**
  - Click tray → "Settings…" → opens a modal (own thread + own `tk.Tk`,
    same pattern as `HotkeyCaptureDialog`).
  - Mirror every tray menu item plus tunables not currently exposed:
    - Hotkey (re-uses `HotkeyCaptureDialog` as a modal field control)
    - Mode (Toggle / Hold)
    - Model (radio buttons)
    - Mic device picker (sounddevice device list)
    - Sounds toggle + volume
    - Overlay: opacity, fill color, accent color, border width, corner
      radius, position. Live preview while editing.
    - Auto-start on login (write/remove the Startup folder shortcut)
  - Live-applies. Persists to `config.json`.
  - Estimate: ~400–500 LOC.
- [ ] **First-run wizard**
  - Trigger: no `config.json` yet.
  - Steps: welcome → mic selection → hotkey capture → model choice →
    done.
  - Estimate: ~200 LOC.
- [ ] **Settings tray entry**: top-level `Settings…` item in the tray
  menu. Mode/Hotkey/Model submenus stay for power users.

### Stretch
- [ ] Live overlay preview pane in the settings window (current overlay
  appears next to the controls; updates as user drags sliders).
- [ ] Export/import config (one button to dump `config.json` to a chosen
  path; one to import).

---

## v0.4.0 — Mac port

Only after v0.3.0 ships. Mac friend not in the initial test cohort, so
no urgency.

### Phase 1 — refactor (no new features, both OSes still on Windows builds)
- [ ] Extract platform shims:
  - `_play_sound_win()` / `_play_sound_mac()` (winsound vs `subprocess afplay`)
  - `_config_dir()` (`%LOCALAPPDATA%` vs `~/Library/Application Support`)
  - `_install_startup()` / `_remove_startup()` (Startup folder `.lnk` vs `~/Library/LaunchAgents/<id>.plist`)
  - Skip the Win32-only paths on Mac (DWM rounded corners, `WS_EX_TRANSPARENT`,
    `RegisterHotKey` probe, `SetProcessDpiAwarenessContext`).
- [ ] Lazy-import `winsound`, `ctypes.windll` to keep file import-clean
  on Mac.

### Phase 2 — Mac-specific work
- [ ] Click-through overlay on Mac via PyObjC `setIgnoresMouseEvents_(True)`.
- [ ] Rounded corners on Mac via `NSWindow.cornerRadius` or canvas-only
  draw (current canvas implementation already works cross-platform).
- [ ] Microphone permission prompt (PyObjC `AVAudioSession`).
- [ ] Accessibility permission prompt (TCC via `tccutil`/manual link to
  System Settings → Privacy → Accessibility).

### Phase 3 — packaging
- [ ] PyInstaller / py2app `.app` bundle.
- [ ] DMG via `create-dmg` or `dmgbuild`.
- [ ] Apple Developer ID + notarization (~$99/yr) — required for
  Apple Silicon Gatekeeper. Without it, Mac friend right-clicks → Open
  → "Run anyway" each install (Intel) or hard-block (M-series).
- [ ] CI matrix: add `macos-latest` runner that builds the `.app` and
  uploads alongside the Windows installer.

### Constraint
Building Mac without a Mac is guesswork. Either borrow the friend's
Mac for one debugging session, or iterate via "try this build → tell me
what broke." Document expected friction in the release notes.

---

## v0.5.0+ — driven by tester feedback

Possible directions, not committed:

- [ ] Code signing on Windows (~$200–400/yr EV cert; removes
  SmartScreen "Unknown publisher" warning).
- [ ] Multilingual dictation (use `large-v3`; auto-detect or per-window
  language pref).
- [ ] Custom vocabulary / domain dictionaries (medical, legal, gamer
  slang, internal product names).
- [ ] AI post-processing (auto-format, fix grammar, summarize) via a
  local LLM or paid API.
- [ ] Voice commands ("new line", "comma", "delete word").
- [ ] App-specific integrations (Slack, Notion, Discord) — direct paste
  into specific text controls instead of generic Ctrl+V.
- [ ] Streaming transcription progress in the overlay (Whisper segments
  arrive in chunks; show them live instead of static "Transcribing").
- [ ] Cross-fade between recording and transcribing overlay states.
- [ ] In-app "Test mic" diagnostic (shows live RMS / level meter from
  the configured device, useful when sister's mic isn't picked up).

### Monetization (research only — no commitment)

Decision today: **stay free + open source on GitHub** through v0.5.0.
Re-evaluate if usage breaks out of the tester circle (10+ daily users
not in the friend network, GitHub stars in double digits).

If monetization is pursued later, the framing should be:

- Free baseline (current feature set).
- Pro tier $5–10 one-time on Gumroad / Lemon Squeezy with a real
  differentiator (custom vocab, voice commands, AI formatting — pick
  one, not all).
- Open competitors to know about: Wispr Flow ($12/mo, well-funded),
  MacWhisper ($25 one-time, Mac), Superwhisper ($79 one-time, Mac),
  VoiceInk ($5/mo), Aiko (free, Mac). Don't compete on "Whisper into
  clipboard" alone — Aiko already does that for free.

---

## Operational notes

### Releasing a new version
1. Make changes, commit, push to `main`.
2. Bump `__version__` in `dictate.py` and `MyAppVersion` in
   `installer.iss` (CI also re-substitutes from the tag, so this is
   belt-and-suspenders).
3. `git tag -a vX.Y.Z -m "..." && git push origin vX.Y.Z`.
4. Watch `gh run list --workflow=release.yml --limit 1`. Build takes
   ~4 min.
5. CI uploads `AriasSTT-Setup-vX.Y.Z.exe` to the GitHub release on its
   own.
6. Edit release notes if needed: `gh release edit vX.Y.Z --notes "..."`.
7. Testers see the update toast within 30 s of their next launch.

### Local manual build (for debugging without tagging)
```
build.bat        # PyInstaller -> dist\AriasSTT\AriasSTT.exe
installer.bat    # iscc installer.iss -> installer-output\AriasSTT-Setup-v*.exe
```
Requires the venv set up via `setup.bat` plus Inno Setup
(`winget install JRSoftware.InnoSetup`).

### Files of interest
- `dictate.py` — single-file app (~1900 LOC).
- `docs/HOTKEY_PLAN.md` — P0–P8 hotkey reliability + UX history.
- `docs/ROADMAP.md` — this file.
- `installer.iss` — Inno Setup script.
- `installer.bat` / `build.bat` — local build scripts.
- `AriasSTT.spec` — PyInstaller spec, regenerated on build.
- `.github/workflows/release.yml` — CI release pipeline.
- `requirements.txt` — Python deps for CI install.
- `CLAUDE.md` — project instructions for future Claude Code sessions.

### Decisions on record
- **No Mac port until v0.4.0.** Windows feature-complete first.
- **No monetization through v0.5.0.** Validate audience first.
- **No code signing yet.** SmartScreen click-through is acceptable for
  the current tester audience.
- **Velopack rejected** in favor of a small custom GitHub-Releases
  poller. Fewer dependencies, sufficient for this scope.
- **PrivilegesRequired=lowest** in installer — per-user install, no
  UAC. Keeps the install flow friction-free for non-technical testers.

### Open questions to revisit after tester feedback
- Is `Ctrl+Alt+Space` the right default? Sister/friend may have
  conflicts we didn't anticipate.
- Is the 220×48 overlay too small? Too big? Position survey: top vs
  top-right vs bottom?
- `medium.en` vs `small.en` — what's the sweet spot for typical user
  hardware?
- Auto-start on login: should the installer's autostart task default
  to checked? Currently checked; test feedback may push us off that.
- Hold-mode discoverability: do testers find it without prompting?
