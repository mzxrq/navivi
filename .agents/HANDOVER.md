# Handover: state after the wrap2 merge and the Sandbox fixes (updated 2026-10-07)

Read this first when you (or Claude) pick the work up.

## 1. Where things stand

PR #32 (`wrap2` into `main`) is **merged** (merge commit `2118322`). All ten first-wave workstreams are on `main`: cleanup, keys, voice, heatmap, overview, pins, look, regen, hudlang, render-output.
What each did, and the non-obvious behaviour, is in `.agents/CODEMAP.md` ("wrap2 additions (2026-10-07)"). The audit status is at the top of `docs/BACKEND_GAPS.md`.
Dead code from the audit is removed (`local_pan_generator.py` stays: `jump_cut.py` and `ltx_keyframed.py` use it). Japanese strings are filled (`npm run extract` shows ja Missing = 0).
Decisions taken: pin icons are built into the video; on-video text defaults to English for English-UI projects ("auto").

CI on the PR was green on all three checks (Frontend, Python pipeline, Rust shell). Tests must never write or download model-sized files (CI and the dev disk can't take GBs); `tests/test_comfyui_setup.py` uses kilobyte specs or sparse files.

Later the same day, a Windows Sandbox run on a clean PC found installer and first-run problems. They are fixed on branch `wrap2leftover` (pushed, **no PR opened yet**; base `main`): static C runtime for the setup exe and the app, a Visual C++ runtime check and install prompt, real import errors from the voice installers, Ollama "Install now" and re-detection, AI setup in first-run setup with the assistant hidden when no model or key is usable, original recording played when a voice engine is not set up, and optional code signing. Details and reasons: `.agents/CODEMAP.md` ("Clean-PC fixes after a Windows Sandbox run"). Tests at the last run: frontend 402, Python 976, cargo 46, setup crate 17, all passing.

## 2. What is left

0. Sandbox follow-up: the new installer has **not** run on a clean PC (Smart App Control blocks any unsigned exe there, the NSIS one too). Test in a Hyper-V Windows 11 VM, or turn Smart App Control off on the host (permanent), or sign the build (`NAVIVI_SIGN_PFX` / `NAVIVI_SIGN_COMMAND`, `scripts/sign.mjs`; needs a certificate from a trusted authority, a self-signed one is still blocked). Then check: the VC++ runtime prompt, a voice install, Ollama "Install now", OpenRouter sign-in, the hidden assistant button. `uninstall.exe` stays unsigned.
0b. The tao panic `assertion failed: flush_paint_messages` (during assistant chat with Ollama) is open upstream (tauri-apps/tao#1140, no repro). Only a mitigation was made (blocking commands moved off the main thread). If it returns, get a `RUST_BACKTRACE=1` trace.
1. Real-app checks nobody has done (everything was verified by tests, the headless harness or jsdom only): the heatmap with terrain, API keys with a real Mapbox key (and the Rust handoff of `NAVIVI_MAPBOX_TOKEN`), pin images in a real pydeck render, a photo clip (the parallax fallback raised OSError 22 on this PC), the new Look and Export dialogs, the overview editor, Voice tab cache, regeneration buttons, a real ComfyUI model download and run.
2. Second wave, **not started**: GPS stay detection on import (controls for radius and minimum stay; `gpsparser/stays.py` and `import_gps_track` exist) and translated subtitles (use the chosen local Ollama model or online provider, off by default, with the disclosure; not `deep-translator`). Branch from current `main`. The old worktrees `.claude/worktrees/wave2-stays` and `wave2-subs` (branches `wrap2-stays`, `wrap2-subs`) are stale: delete them.
3. Manuals: `Documents\Navivi-Manual\Navivi_User_Manual_EN_wrap2.docx` and `_JA_wrap2.docx` exist (text only, not in git). Screenshots predate the new controls. Chapters changed are listed in section 3.
4. Cleanup (optional): delete the merged local branches `wrap2` and `wrap2-*` and the worktrees under `.claude/worktrees/`.
5. Open points from the engineers: overview "Hear it" on a stale auto script rewrites the script on disk while the app keeps the old text; no cancel for Auto-write; `ollamaApi.generateOverviewScriptStream` is dead; `raw_track.gpx` still writes a fake `<ele>35.0`; a frame rate other than 30 in `fps` now exports at that rate; voice style names (まじめ, あたたかい, 元気) and a few other Japanese strings are guesses; British spelling in "Text colour" and "Outline colour" strings; `docs/BACKEND_GAPS.md` section 5 still lists `local_pan_generator` as nearly dead (the status table at the top corrects this).

## 3. Manual changes covered

Mapbox/OpenRouteService sharing warning rewritten in chapters 3 and 14 (keys are app-wide and never in projects). Added: elevation heatmap, Voice tab (speaking style, 0.25-4x speed, cues, cache), overview narration editor, pin images in the video, Look of the video (+ per-stop options), Make everything again and per-stop regeneration, on-video text language, export options, map style in the video.

## 4. Environment notes

- Windows + Git Bash. The Bash tool mangles backslashes in inline `python - <<EOF` and `sed` programs: write such scripts to a file and run them.
- Run Python tests with the system `python`. `npm test` needs `node_modules`; Lingui CLI needs Node 24. If a test fails with "No space left on device", clear `%TEMP%\pytest-of-*`.
- One Python sidecar call at a time (Rust kills the previous one).
- Sub-agents: `isolation: worktree` branches from `origin/main`, so for work on another branch use an existing git worktree by absolute path; a junction for `node_modules`; separate `CARGO_TARGET_DIR` under `src-tauri/target-agents/`. Keep at most 3 to 4 running; ten at once hit the rate limit.
- Task prompts and engineer rules from the first wave: `.agents/handover/tasks.md`, `.agents/handover/agent_rules.md`.
- Screens are checked with the headless harness `.agents/scratch/overlay-check/index.html`. Do not start the real app from an agent.
- Never commit to `main`; work on a branch and open a PR. No Co-Authored-By or "Generated with" lines.
- Memory (preferences, what the user has confirmed) lives outside the repository in Claude's project memory folder.
