# Auritus — Gumroad listing

> Go-live checklist:
> 1. Product file to upload: `Auritus-Setup-v0.3.3.exe` — pull from GitHub Releases:
>    `gh release download v0.3.3 -R Nyavix/Auritus -p '*.exe'`
>    (direct: https://github.com/Nyavix/Auritus/releases/download/v0.3.3/Auritus-Setup-v0.3.3.exe)
> 2. Price: **$19 launch** (bump to $29 later). One-time, not subscription.
> 3. Add 2-3 screenshots + a short tray-in-action GIF before publishing.
> 4. Set a refund policy (fills the [set your policy] line below).
>
> Note: Gumroad's API can't create a product listing (creation endpoint 404s), so
> this gets pasted into the dashboard by hand, or driven through a logged-in browser.

---

## Title
Auritus — Local Whisper Dictation for Windows

## Summary
Press a hotkey, talk, and your words show up in whatever you're typing into. Whisper runs on your own machine, so nothing gets uploaded and there's no account to make. Works on plain CPUs and AMD GPUs, not just NVIDIA.

## Description

I built this because every "just use local dictation" recommendation assumed I had an NVIDIA card. My machine runs an AMD Radeon, and most of those tools either refused to start or crawled. So I made one that doesn't care what GPU you have.

Here's how it works. Press Ctrl+Alt+Space, say what you're thinking, press it again. Auritus transcribes your voice with Whisper on your own computer and pastes the text straight into Notepad, your browser, Slack, your editor, an email, wherever the cursor happens to be. No browser tab, no sign-in, no monthly fee. Your audio never leaves the machine.

What you're actually getting:

- It runs locally. Transcription happens on your CPU or GPU. Nothing is uploaded. The only time it touches the network is the one-time model download on first launch.
- It doesn't need an NVIDIA card. CPU works out of the box. If you have an AMD or Intel GPU, it uses that through Vulkan and runs faster.
- You pay once. No subscription.
- It lives in your system tray as a small dot. Set your hotkey, model, and accuracy from the tray menu.
- Toggle mode for long dictation, hold mode for quick bursts. Your call.

What's in the download:

- `Auritus-Setup-v0.3.3.exe`, a one-click installer with both the CPU and GPU backends bundled in.
- An option to auto-start when you log in.
- Free updates across v0.x.

What you need:

- Windows 10 or 11
- A microphone
- About 2 GB free for the speech model
- An internet connection for the first model download, then you're offline

A few honest notes:

- First launch pulls the `medium.en` model (about 1.5 GB) once, then works with no connection.
- `medium.en` is accurate but not the fastest. On an older machine, switch to `small.en` or `base.en` from the tray and you'll barely notice the accuracy drop on short dictation.
- Some apps that run as administrator block the auto-paste. When that happens your text is already on the clipboard, so Ctrl+V finishes the job.

Questions people ask:

- Does my audio go anywhere? No. It's transcribed on your machine. The only network call is the first model download.
- Do I need a GPU? No, CPU is fine. Any Vulkan GPU just makes it faster.
- Mac or Linux? Windows only right now.
- Refunds? [set your policy]
