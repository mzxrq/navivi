# Handover: state of the wrap2 push (written 2026-10-06, session limit hit)

Read this first when you (or Claude) pick the work up on another PC. It says what is finished, what is half done, where every
piece of half-done work lives, and what to do next. Everything referenced here is either in git (branch `wrap2` on GitHub) or in
the handover zip (`navivi-handover-*.zip`: it contains `wip-branches.bundle` for the unfinished branches).

## 1. Where things stand

| Item | State |
|---|---|
| Branch `wrap2` (origin) | = `main` at `c48fc07` + one commit `e4bc4b6`: the developer guide, the backend-gaps report, the agent notes in `.agents/` and `.claude/CLAUDE.md`. Pushed. The commit after it adds this handover and `.gitignore` tweaks |
| Tests at `e4bc4b6` | frontend: tsc clean, 33 files / 289 tests pass. Python: the baseline run was still going when the session ended (it passed on the earlier branch; run `python -m pytest -q` in `src-tauri/src-python` to confirm) |
| User-visible work done earlier this session (already on `main`) | assistant chat saved per project; photo finder (Wikimedia) with credits; Gemma 4 in the Ollama list; Setup tab with model names, credits and the ComfyUI installer; static C runtime + VC++ check in the setup program; the `popup_image` fix; AI-choice load retry; PR template |
| The ten engineers (see section 3) | all ten stopped when the session limit hit. Seven left partial work, saved as one WIP commit per branch. **Nothing from them is merged into `wrap2` yet** |

## 2. What was decided this session (keep these)

- **Keys** (answer to "why are the Mapbox/OpenRouteService tokens stored in the project settings?"): it is a design flaw. They were put in
  `ProjectSettings` before the AI keys got proper handling. Decision: make both **app-wide** (DB app setting `api_keys`, merged into `settings`
  like `ai_settings`), never written into `job_config.json`, the project DB row, version snapshots or a `.nvv`; adopt a key found in an old project
  once; scrub archives; Rust hands the Mapbox token to Python as `NAVIVI_MAPBOX_TOKEN`. Work in progress on branch `wrap2-keys`.
  After it lands, **change the manual sentence** in chapters 3 and 14 ("Remove your Mapbox and OpenRouteService tokens ... before sharing"): it will no longer be true.
- **Agent notes** live in git, inside folders only: `.agents/` (CLAUDE.md, CODEMAP.md, TECH_STACK.md, handover/, scratch/overlay-check) and
  `.claude/CLAUDE.md` (one line importing `../.agents/CLAUDE.md`). No `CLAUDE.md` in the repository root.
- Git rules (user's): never commit to `main`; work and push on the branch the user made for you (now `wrap2`); no `Co-Authored-By` or
  "Generated with" lines; commit subjects `feat:` / `fix:` / `chore:` / `docs:`.
- The elevation heatmap is reported "not working properly" by the user, with no more detail. Engineer `heatmap` was to find out.
- Decisions still open for the user: pin icons (build in the video renderer or hide the controls; engineer `pins` was to decide with evidence);
  English on-video text becomes the default for English-UI projects ("auto"; Japanese projects stay unchanged).

## 3. The ten workstreams and where their unfinished work is

Task text for each: `.agents/handover/tasks.md`. Shared rules: `.agents/handover/agent_rules.md`.
Branches are named `wrap2-<name>` (git cannot have both `wrap2` and `wrap2/x`). Restore them from the bundle (section 5) or find them in the
original checkout. Every branch starts at `wrap2` `e4bc4b6` (cleanup has two real commits first).

| Branch | What it should deliver | What is on the branch now | Verdict |
|---|---|---|---|
| `wrap2-cleanup` | small bug fixes + dead-code removal | **Two finished commits**: `ba078b4` Fly legs behave as airplane legs (`tuning.py` `MODE_ALIASES`, test), `5d2a5a8` overview narration uses the chosen local model (`script_engine.py`, test). Then a WIP commit `269846b` (19 files): `marker_radius` default (`constants.ts`, `base.py`, test), `imageTransitions` removal (types, saver, loader, `manifestBuilder.ts`), `main.py` payload split + test, `test_online_llm.py` edits. No dead-code deletions yet (verify before doing them: see the task) | review, run tests, merge the two good commits first |
| `wrap2-keys` | app-wide Mapbox/ORS keys | WIP commit (21 files): `src/utils/apiKeys.ts`, `src/hooks/useAppApiKeys.ts`, edits in `AppSettings.tsx`, `useWorkspace.tsx`, `fileSystem.ts`, `projectStore.ts`, `versionHistory.ts`, Rust `lib.rs`, `db/app_settings.rs`, `project_files.rs`; Python `services/mapbox_token.py` + `test_mapbox_token.py`, token plumbing in `maptile.py`, `pydeckrecorder/*`, `route2vdo.py`, `transitions.py`. It was in the middle of "the hook". Not compiled/tested to completion | most advanced big item: finish, `cargo test`, `npm test`, pytest |
| `wrap2-voice` | speaking style, caption extras, cue helpers, voice cache, speed range | WIP (4 files): Python side only: `voice_commands.py` + `phrase_cache.py` (cache info/clear), `test_voice_extras.py`, `test_caption_look_burn.py`. No UI yet | Python half done; the Voice-tab UI, caption fields and cue buttons are still to do |
| `wrap2-overview` | overview narration editor | WIP (4 files): Python only: `main.py`, `script_commands.py`, `narration_step.py`, `test_overview_script_mode.py`. No panel yet | UI (`OverviewPanel.tsx`), persistence and the ReviewStep sentence still to do |
| `wrap2-pins` | custom pin icons in the video | WIP: new `graphicengine/pinimage.py` (225 lines, image pin drawing helper). Not wired into the renderers, no test | started |
| `wrap2-render-output` | export options + video map style | WIP (3 files): small edits in `mapfetcher.py`, `maplanguage.py`, `transitions.py` (style plumbing start). Nothing for the export dialog yet | barely started |
| `wrap2-heatmap` | fix the elevation heatmap | only a stray `hm-shoot.mjs` harness script. The investigation findings were lost | start again |
| `wrap2-hudlang` | English text in the video | nothing saved | start again |
| `wrap2-regen` | force option + per-stop regeneration | nothing saved (it had been timing the single-stop CLI modes) | start again |
| `wrap2-look` | video look settings | nothing saved (it had only read code) | start again |

Merge order that limits conflicts: cleanup, keys, then the others one by one (each touches `types/index.ts`, `constants.ts`, `render_step.py`,
`tuning.py`, `ProjectSettingsModal.tsx`, `WaypointEditor.tsx`; expect small conflicts, resolve by keeping both sides). After each merge run
`npm run typecheck && npm test`, and the pytest files for the area.

## 4. What the lead still has to do (not delegated)

1. Merge the branches into `wrap2`, resolve conflicts, run all three suites (frontend, `python -m pytest -q`, `cargo test --manifest-path src-tauri/Cargo.toml`).
2. `npm run extract`, then fill the Japanese `msgstr` entries in `src/locales/ja/messages.po` (helper scripts used before: `list_missing.py` / `ja_fill2.py` pattern: find empty msgstr, map msgid -> Japanese, rewrite), `npm run compile`.
3. Update `.agents/CODEMAP.md` with the notes from each engineer, and `docs/DEVELOPER_GUIDE.md` / `docs/BACKEND_GAPS.md` (mark fixed items).
4. Update the user manuals (`Documents\Navivi-Manual\Navivi_User_Manual_EN.docx` / `_JA.docx`; the newest text is in the `*_updated.docx` copies because the originals were open in LibreOffice). Edit the XML with lxml like the earlier scripts (single-run replacements; keep image paragraphs by cloning); validate with the docx skill's `validate.py`; render through Word COM for a visual check. New things to cover: app-wide keys (rewrite the sharing warning), new settings, regenerate options, overview editor, export options, English on-video text, heatmap.
5. Second wave: GPS stay detection, translated subtitles (see the end of `tasks.md`).
6. Open a PR `wrap2` -> `main` (base `main`, head `wrap2`; the template is `docs/pull_request_template.md`).

## 5. Getting the unfinished branches on another PC

The zip contains `wip-branches.bundle` (only the new commits, small). After cloning the repository and checking out `wrap2`:

```bash
git clone https://github.com/mzxrq/navivi && cd navivi && git checkout wrap2
git fetch ../wip-branches.bundle "refs/heads/wrap2-*:refs/heads/wrap2-*"      # path to the bundle from the zip
git branch --list "wrap2-*"
git log --oneline wrap2..wrap2-keys                                           # look at one
git merge wrap2-cleanup                                                       # etc.
```

The bundle also holds the salvaged WIP commits; each WIP commit message says it is unreviewed. Treat them as drafts.

## 6. Environment notes for whoever continues

- Windows + Git Bash. The Bash tool mangles backslashes in inline `python - <<EOF` and `sed` programs: write scripts that contain a backslash to a file (Write tool) and run it; use `chr(92)`.
- Run Python tests with the system `python` (the repository `.venv` has no packages). `npm test` needs `node_modules`; Lingui CLI needs Node 24.
- One Python sidecar call at a time (Rust kills the previous one): never start a second `callSidecar` while another runs.
- Sub-agents in worktrees need a junction for `node_modules` (see `agent_rules.md`) and a separate `CARGO_TARGET_DIR`.
- Screens are checked with the headless harness `.agents/scratch/overlay-check/index.html` (see the developer guide, section 3). Do not start the real app from an agent.
- Session memory (preferences and what the user has confirmed) lives outside the repository in Claude's project memory folder; the zip contains a copy
  under `claude-memory/`. Copy it back to `%USERPROFILE%\.claude\projects\<project folder name>\memory\` if you want Claude to remember it on the other PC.

## 7. Not yet tried by a human in the real app

Assistant chat history, the photo finder, the Setup tab rewrite, the ComfyUI installer (never run: 26 GB, needs a GPU), the VC++ runtime check in the setup
program (needs a clean Windows Sandbox), the `popup_image` save fix (existing projects need one resave), and everything on the WIP branches.
