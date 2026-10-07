# Handover: state of the wrap2 push (updated 2026-10-07)

Read this first when you (or Claude) pick the work up. Everything below is in git on branch `wrap2` (GitHub) unless noted.

## 1. Where things stand

All ten first-wave workstreams are **merged into `wrap2`** and pushed: cleanup, keys, voice, heatmap, overview, pins, look, regen, hudlang, render-output.
What each did, and the non-obvious behaviour, is in `.agents/CODEMAP.md` ("wrap2 additions (2026-10-07)"). The audit status is at the top of `docs/BACKEND_GAPS.md`.
Dead code from the audit is removed. Japanese strings are filled (`npm run extract` shows ja Missing = 0). Decisions taken: pin icons are built into the video; on-video text defaults to English for English-UI projects ("auto").

Test state at the last full runs: `npx tsc --noEmit` clean, `npm test` 54 files / 389 tests pass. Python: 909 passed and 1 failed (the ComfyUI setup test, which ran out of disk; since rewritten to write kilobytes: 16 passed).
A full `python -m pytest -q` after the very last merges was started but its result was not seen: run it once (`cd src-tauri/src-python`; about 9 minutes). `cargo test` last passed (46) on the keys branch before the other merges.

## 2. What is left

1. Run the three suites on `wrap2` (frontend, `python -m pytest -q`, `cargo test --manifest-path src-tauri/Cargo.toml`). If a test fails with "No space left on device", clear `%TEMP%\pytest-of-*`.
2. Manuals: an agent was writing `Documents\Navivi-Manual\Navivi_User_Manual_EN_wrap2.docx` and `_JA_wrap2.docx` (new copies of the `*_updated.docx` files; text only, no new screenshots). Check they exist and open; otherwise redo with the list in section 3.
3. Second wave, **not started** (the two engineers were stopped before writing any code to save quota): GPS stay detection on import (controls for radius and minimum stay; `gpsparser/stays.py` and `import_gps_track` exist) and translated subtitles (use the chosen local Ollama model or online provider, off by default, with the disclosure; not `deep-translator`). Worktrees `.claude/worktrees/wave2-stays` and `wave2-subs` (branches `wrap2-stays`, `wrap2-subs`, same as `wrap2` at that time) can be reused or deleted.
4. Real-app checks nobody has done (everything was verified by tests, the headless harness or jsdom only): the heatmap with terrain, API keys with a real Mapbox key (and the Rust handoff of `NAVIVI_MAPBOX_TOKEN`), pin images in a real pydeck render, a photo clip (the parallax fallback raised OSError 22 on this PC), the new Look and Export dialogs, the overview editor, Voice tab cache, regeneration buttons.
5. Open points from the engineers: overview "Hear it" on a stale auto script rewrites the script on disk while the app keeps the old text; no cancel for Auto-write; `ollamaApi.generateOverviewScriptStream` is dead; `raw_track.gpx` still writes a fake `<ele>35.0`; a frame rate other than 30 in `fps` now exports at that rate; voice style names (まじめ, あたたかい, 元気) and a few other Japanese strings are guesses; British spelling in "Text colour" and "Outline colour" strings.
6. Open the PR: base `main`, head `wrap2`, text from `docs/pull_request_template.md`. Never commit to `main`; no Co-Authored-By or "Generated with" lines.

## 3. Manual changes to cover (if redoing)

Rewrite the Mapbox/OpenRouteService sharing warning in chapters 3 and 14 (keys are app-wide and never in projects). Add: elevation heatmap, Voice tab (speaking style, 0.25-4x speed, cues, cache), overview narration editor, pin images in the video,
Look of the video (+ per-stop options), Make everything again and per-stop regeneration, on-video text language, export options, map style in the video.

## 4. Environment notes

- Windows + Git Bash. The Bash tool mangles backslashes in inline `python - <<EOF` and `sed` programs: write such scripts to a file and run them.
- Run Python tests with the system `python`. `npm test` needs `node_modules`; Lingui CLI needs Node 24.
- One Python sidecar call at a time (Rust kills the previous one).
- Sub-agents: use existing git worktrees by absolute path (the `isolation: worktree` default branches from `origin/main`, not `wrap2`); a junction for `node_modules`; separate `CARGO_TARGET_DIR` under `src-tauri/target-agents/`. Keep at most 3 to 4 running; ten at once hit the rate limit.
- Task prompts and engineer rules from the first wave: `.agents/handover/tasks.md`, `.agents/handover/agent_rules.md`.
- Screens are checked with the headless harness `.agents/scratch/overlay-check/index.html`. Do not start the real app from an agent.
- Memory (preferences, what the user has confirmed) lives outside the repository in Claude's project memory folder.
