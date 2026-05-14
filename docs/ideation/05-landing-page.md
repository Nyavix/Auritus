---
id: 05-landing-page
title: Landing page
status: draft
target: v1.0.0
prd-section: §7
companion-html: 05-landing-page.html
last-updated: 2026-05-14
---

# Landing page

> Public-facing page that pitches AriasSTT, links the latest release, and
> demos the overlay in motion.

## 1. Purpose

GitHub Releases is the source of truth for downloads, but a release page
is not a sales pitch. Landing page is where someone outside the tester
circle first hears "Whisper into clipboard, free, offline, Windows" and
clicks Download.

## 2. User stories

- As a visitor, I want to understand what AriasSTT does within 5
  seconds of landing.
- As a visitor, I want a one-click download from the hero.
- As a visitor, I want to see the overlay in action without installing.

## 3. Functional spec

### 3.1 Trigger
URL hit. Hosting TBD — GitHub Pages, Vercel, or `arias.studio/stt`.

### 3.2 States
Static page. No client-side state beyond hover / scroll.

### 3.3 Inputs
- "Download" CTA → latest GitHub release installer.
- "GitHub" link → repo.
- Optional: copyable hotkey snippet, video / GIF replay button.

### 3.4 Outputs
None server-side. May log download clicks if hosting supports it.

### 3.5 Edge cases
- Release URL rot — "Download latest" should always link to
  `/releases/latest/download/AriasSTT-Setup.exe` (GitHub redirects).
- No-JS visitors — page must function (CTA + content). Hero animation
  is progressive enhancement.

## 4. Visual design

PRD §7 sections, refined:

```
┌────────────────────────────────────────────────────┐
│  AriasSTT                                  GitHub  │
├────────────────────────────────────────────────────┤
│                                                    │
│     Whisper into clipboard.                        │
│     Free. Offline. Windows.                        │
│                                                    │
│     [ Download for Windows ]   [ View on GitHub ]  │
│                                                    │
│            ┌── overlay-in-motion GIF ──┐           │
│            │  ▁▂▃▅▇█▇▅▃▂▁              │           │
│            └───────────────────────────┘           │
├────────────────────────────────────────────────────┤
│  How it works                                      │
│    1. Press hotkey   2. Speak   3. Text appears    │
├────────────────────────────────────────────────────┤
│  Features                                          │
│    • Push-to-talk + meeting mode                   │
│    • GPU (Vulkan: AMD / NVIDIA / Intel) or CPU     │
│    • 100% offline, no telemetry                    │
│    • One-click installer, auto-updates             │
├────────────────────────────────────────────────────┤
│  Download                                          │
│    Latest: v1.0.0 — Windows 10/11                  │
│    [ AriasSTT-Setup-v1.0.0.exe ]                   │
│    sha256: ...                                     │
├────────────────────────────────────────────────────┤
│  Footer — GitHub · License (MIT) · v1.0.0          │
└────────────────────────────────────────────────────┘
```

### 4.1 Tokens
- Page bg: `#0a0a0a` (matches overlay)
- Accent: `#ff6868` (matches wave)
- Body: TBD font (Inter? system stack?)
- Hero asset: animated GIF or `<video>` loop of the overlay in motion.

### 4.2 Companion HTML
Open `05-landing-page.html` for a click-through prototype.

## 5. Acceptance criteria

- [ ] Hero loads with CTA + headline above the fold on a 1280×720 screen.
- [ ] "Download" links to `/releases/latest/download/AriasSTT-Setup.exe`.
- [ ] "How it works" shows 3 steps with icons or screenshots.
- [ ] Features list mirrors PRD §6.1 shipped highlights.
- [ ] Footer shows version pulled from the latest tag (manual or
      automated via build step — TBD).
- [ ] Page passes Lighthouse perf ≥ 90 on mobile.
- [ ] Works without JS (graceful degradation).

## 6. Open questions

| # | Question | Blocking? | Resolution |
|---|----------|-----------|------------|
| 1 | Hosting: GitHub Pages vs Vercel vs arias.studio/stt? (PRD §9) | y | |
| 2 | Hero asset: GIF, MP4 loop, or live HTML overlay demo? | n | |
| 3 | Auto-update the version label, or accept manual edits per release? | n | |
| 4 | Single page or multi-page (docs, changelog separate)? | n | |

## 7. Dependencies

- Modules: [04-branding-icons](04-branding-icons.md) (page uses the
  designed icon).
- External: hosting decision, optional video capture tool for hero asset.

## 8. Status log

- 2026-05-14 — created (draft)
