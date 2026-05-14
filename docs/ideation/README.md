# Ideation

Module-by-module design workspace. Each major feature milestone gets its own
module here. We zone in on one at a time — purpose, function, look, feel —
until it's locked, then push the resolved spec into `docs/PRD.md` and let
development cite the module on every PR.

## Workflow

1. **Pick a module** from the index below (work top-to-bottom unless a
   dependency says otherwise).
2. **Open the module's `.md`** — fill the template fields in order. Use
   ASCII mockups for layout. Iterate freely; status stays `draft`.
3. **If the module is visual / interactive**, open the matching `.html`
   alongside it. The HTML is a clickable mockup (Tailwind via CDN — open
   directly in a browser, no build step). Use it to feel transitions,
   states, and hover behavior the ASCII can't show.
4. **Lock the module** when both the `.md` spec and the `.html` mockup
   answer every open question. Change `status:` to `locked`.
5. **Push to PRD.** Copy the locked sections (purpose, functional spec,
   acceptance criteria) into `docs/PRD.md` §6.x. Keep the ideation file
   intact as the source of truth for the design rationale.
6. **Development cycle.** Every PR that touches a locked module cites
   `docs/ideation/NN-name.md#acceptance-criteria` in its description.
   When a checkbox there is met, tick it off. Module status flips to
   `shipped` when all criteria are checked + tag is cut.

## Module index (v1.0 scope)

| #  | Module                                    | Status | .html | Notes |
|----|-------------------------------------------|--------|-------|-------|
| 01 | [First-run wizard](01-first-run-wizard.md)| draft  | ✅    | PRD §6.2 Feature A |
| 02 | [Settings GUI](02-settings-gui.md)        | draft  | ✅    | PRD §6.2 Feature C |
| 03 | [Meeting recording](03-meeting-recording.md)| draft| ✅    | PRD §6.2 Feature B |
| 04 | [Branding & icons](04-branding-icons.md)  | draft  | ✅    | PRD §6.2 Feature D |
| 05 | [Landing page](05-landing-page.md)        | draft  | ✅    | PRD §7 |

Future scope (v1.1+, not yet drafted): overlay-preview, mic-tester,
config-export-import. Drop into this index when they get promoted.

## Conventions

- **File naming:** `NN-kebab-name.md` + optional `NN-kebab-name.html`.
- **HTML:** single file, Tailwind via CDN (`<script src="https://cdn.tailwindcss.com"></script>`).
  No build, no bundler. Opens in a browser straight from disk.
- **Mockup units in the .md:** width × height in px, color hex,
  font + size, opacity. Match the existing overlay tokens
  (`OVERLAY_FILL_COLOR #0a0a0a`, `OVERLAY_ACCENT #ffffff`,
  `OVERLAY_WAVE_COLOR #ff6868`) unless the module is explicitly
  introducing new tokens.
- **Status values:** `draft` → `locked` → `shipped`.
- **One open question per row.** If a question blocks the module, surface
  it; don't bury decisions.
- **Don't bypass.** Skipping a module straight to code re-opens design
  arguments mid-PR. The ideation file is the place to lose those
  arguments cheaply.
