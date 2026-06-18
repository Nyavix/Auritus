# Auritus — Product Requirements Document

**Version:** 1.0-draft  
**Date:** 2026-05-10  
**Status:** Active

---

## 1. Product Overview

Auritus is a free, open-source Windows tray application that converts speech to text locally — no cloud, no subscription, no data sent anywhere. It targets anyone who types a lot or attends meetings and wants a fast, private, offline alternative to cloud dictation services.

It is part of the **Arias ecosystem** and will be designed and branded accordingly.

---

## 2. Problem Statement

People who type for a living (writers, students, office workers, developers) spend significant time converting their own voice into text — in meetings, during note-taking, or while dictating messages. Existing solutions require:

- A cloud subscription (Whisper Flow, Otter.ai)
- A Mac (MacWhisper, Superwhisper)
- An NVIDIA GPU (most local Whisper tools)
- Deep technical setup (running Whisper from the command line)

Auritus eliminates all four barriers: **local, Windows, GPU-agnostic (AMD/NVIDIA/Intel/CPU), one-click install.**

---

## 3. Target User

**Primary:** Anyone who types a lot on Windows — writers, students, professionals, office workers — who wants to save time and reduce strain without sending audio to a cloud service.

**Secondary:** Meeting attendees who need a passive transcription of long sessions saved to their Documents folder for later reference or note-taking.

**Non-target (v1.0):** Enterprises requiring multi-user licensing, compliance frameworks, or centralized deployment.

---

## 4. Brand Identity

- **Name:** Auritus (short-form: Arias)
- **Brand family:** Part of the Arias ecosystem
- **Tone:** Friendly, accessible, approachable — plain language, warm design, built for non-technical users without dumbing down for technical ones
- **Distribution:** GitHub Releases (primary) + landing page (secondary)
- **License:** Open source, free forever

---

## 5. Success Metrics (v1.0)

| Metric | Target |
|---|---|
| New user can complete first successful dictation | Within 3 minutes of install, zero config required |
| Meeting transcript quality | Readable, timestamped, correctly saved to Documents |
| Installer friction | SmartScreen click-through acceptable; no actual errors |
| Update delivery | Users on v1.0 receive v1.1 automatically within 30s of next launch |
| Support burden | Friends/family can self-diagnose from tray menu + log folder |

---

## 6. Feature Scope

### 6.1 Already shipped (v0.1–v0.3)

- Push-to-talk hotkey (toggle + hold modes)
- Cancel hotkey (default `<ctrl>+<f9>`) — abort active recording or drop in-flight transcription before clipboard/paste
- faster-whisper CPU inference (int8, medium.en default)
- whisper.cpp GPU inference via Vulkan (AMD/NVIDIA/Intel — auto-detect)
- Backend tray submenu (Auto / GPU / CPU)
- Model tray submenu (tiny.en → large-v3)
- Hotkey tray submenu + custom capture dialog
- Live waveform overlay (glass panel, configurable)
- Auto-update via GitHub Releases polling
- One-click Inno Setup installer
- GitHub Actions release pipeline (tag → build → upload)
- Version label in tray menu

### 6.2 v1.0 — Must-have before wide sharing

#### Feature A: First-Run Setup Wizard

**Trigger:** No `config.json` exists (fresh install).

**Steps:**
1. **Welcome screen** — "Welcome to Auritus. Let's set up in 60 seconds."
2. **Mic selection** — List of detected audio devices; default highlighted. Test button plays a level meter.
3. **Hotkey selection** — Preset list with the HotkeyCaptureDialog for custom. Warning shown for known conflicts (Teams, Discord).
4. **Model choice** — Three options: Fast (small.en), Balanced (medium.en, default), Accurate (large-v3). Shows estimated first-download size and speed tradeoff.
5. **Backend choice** — Auto (recommended), GPU, CPU. GPU greyed if binary absent.
6. **Done** — "You're set. Press [hotkey] to start dictating." Config written. Wizard closes.

**Implementation notes:**
- Same `tk.Tk` + own thread pattern as `HotkeyCaptureDialog`
- Must not block the tray icon
- If user closes wizard without finishing, default config is used (same as today)

#### Feature B: Meeting Recording Mode

**What it is:** A long-session audio capture triggered by a separate hotkey (or tray menu item). When stopped, the full audio is transcribed and saved as a formatted Markdown file.

**Behavior:**
- Separate hotkey from push-to-talk (configurable, default: `<ctrl>+<alt>+<shift>+<space>`)
- OR accessible via tray menu: "Start meeting recording" / "Stop & transcribe"
- While recording: tray icon pulses or shows a distinct color (e.g. green dot); overlay shows "Meeting recording..." + duration timer
- When stopped: transitions to "Transcribing..." state; transcription runs on a background thread
- On completion: saves file to `Documents\Auritus\meetings\YYYY-MM-DD_HH-MM.md`
- Notification: "Meeting transcript saved → Documents\Auritus\meetings\..." with a clickable "Open folder" action

**Transcript format:**

```markdown
# Meeting — 2026-05-10 14:32

**Duration:** 47m 12s  
**Model:** medium.en · GPU (whisper.cpp Vulkan)

---

[00:00:00] Good morning everyone, let's get started with the agenda.

[00:01:14] So the first item is the Q2 roadmap review...

[00:04:52] I think we should prioritize the settings GUI before the landing page...
```

**Constraints:**
- Max session length capped at `MEETING_MAX_MINUTES` (config constant, default 120 min)
- Audio buffered in memory during recording; flush to temp file if >500 MB
- Model used is the currently selected model (not a separate model for meetings)
- Single meeting recording at a time; attempting to start another while one is active shows an error toast

#### Feature C: Settings GUI Window

**Trigger:** Tray menu → "Settings…"

**Panel contents:**
- Hotkey (re-uses HotkeyCaptureDialog as a field control)
- Cancel hotkey (re-uses HotkeyCaptureDialog; warn if equal to main hotkey — cancel auto-disables on collision)
- Trigger mode (Toggle / Hold radio)
- Model (radio buttons)
- Backend (Auto / GPU / CPU radio)
- Mic device (dropdown from sounddevice list + test button)
- Meeting hotkey
- Sounds toggle + volume slider
- Overlay: opacity, fill color, accent color, border width, corner radius, position (top / bottom)
- Auto-start on login (checkbox — writes/removes the Startup folder shortcut)
- Open log folder button
- About section: version, GitHub link

**Implementation notes:**
- Own `tk.Tk` + own thread
- Live-applies all settings; persists to `config.json` on each change
- Resize to fit content; not resizable by user
- Estimate: ~400–500 LOC

#### Feature D: Proper App Branding

- **Tray icon:** Designed icon set (idle blue, recording red, transcribing amber) — replace current programmatic dots with actual icon files bundled in the installer
- **App icon:** Used by the installer shortcut and taskbar
- **About entry:** Already added (v0.3.0) — version label in tray
- **Landing page:** See section 7

---

### 6.3 v1.1 — Post-launch polish (driven by feedback)

- [ ] Live overlay preview in Settings window
- [ ] Export / import config
- [ ] "Test mic" level meter in Settings
- [ ] Mic permission / audio troubleshooter toast
- [ ] Meeting transcript post-processing option (AI summarization via local LLM or API — opt-in)

### 6.4 Out of scope for v1.0

- Code signing (SmartScreen click-through acceptable for current audience)
- Multi-language dictation (large-v3 supports it; expose via Settings in v1.1)
- Mac / Linux port (v0.4.0 roadmap item — after v1.0 ships)
- Voice commands ("new line", "comma")
- Speaker diarization (who said what in meetings)
- SaaS / accounts / cloud sync

---

## 7. Landing Page

**URL:** GitHub Pages or Vercel (ariasstt.com or arias.studio/stt TBD)

**Sections:**
1. **Hero** — One-line value prop + download button + platform badge (Windows)
2. **How it works** — 3-step visual: press hotkey → speak → text appears
3. **Features** — Push-to-talk, meeting mode, GPU acceleration, 100% offline, free
4. **Download** — Latest release button + GitHub link + system requirements
5. **Footer** — GitHub, license, version

**Tone:** Friendly, plain language. No jargon. Screenshot or short GIF of the overlay in action.

---

## 8. Release Plan

| Version | Theme | Key deliverables |
|---|---|---|
| v0.3.0 ✅ | GPU backend | whisper.cpp Vulkan, Backend submenu, version label |
| v1.0.0 | Shippable product | First-run wizard, Settings GUI, Meeting mode, branded icons, landing page |
| v1.1.0 | Polish | Feedback-driven: live overlay preview, mic tester, AI meeting summary (opt-in) |
| v0.4.0* | Mac port | Platform shims, py2app, CI matrix (*after v1.0 ships) |

---

## 9. Open Decisions

| Decision | Options | Notes |
|---|---|---|
| Meeting hotkey default | `<ctrl>+<alt>+<shift>+<space>` vs tray-only | Hotkey avoids menu hunting; tray is safer for first release |
| Speaker diarization | v1.0 or v1.1 | Requires pyannote or similar — heavy dep, skip v1.0 |
| Landing page domain | ariasstt.com vs arias.studio/stt vs GitHub Pages | Depends on broader Arias ecosystem plans |
| Branding assets | Who designs the icon/logo? | Needs a visual design pass before v1.0 |
| SmartScreen signing | Skip vs $200/yr EV cert | Skip for v1.0; revisit if distribution grows |

---

## 10. Constraints

- No new runtime dependencies without strong justification (current stack is already heavy)
- All user data stays local — no telemetry, no cloud, no accounts
- Installer must remain a single `.exe` (no separate runtime downloads at install time, except model files on first run)
- App must run on Windows 10 and Windows 11 without admin rights (current: PrivilegesRequired=lowest)
