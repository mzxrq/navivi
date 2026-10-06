# Rules for every engineer on the wrap2 push (read this first, then your task)

You are one of ten engineers working in parallel on **Navivi** (Tauri v2 desktop app: React + TypeScript frontend in `src/`,
Rust shell in `src-tauri/src/`, Python pipeline in `src-tauri/src-python/`). The lead merges your branch afterwards.

## Read before you start
1. `.agents/CLAUDE.md` in your worktree: the house rules (lean comments; American English; icons only through
   `components/ui/icons.tsx`; shared widgets Slider, Switch, Dialog, ContextMenu, Segmented, Checkbox, Tip; Lingui for every
   user-visible string; edit files with Edit/Write, never regex "patch scripts"; UTF-8 without BOM).
2. `docs/DEVELOPER_GUIDE.md`: a map of the code and recipes (add a Waypoint field = four places; add a setting; add a Python mode; ...).
3. `docs/BACKEND_GAPS.md`: the audit that produced your task. Your items are quoted in the task. The audit is a reviewer's reading of the
   code: **re-verify every claim you rely on** with a search or a test before building on it. Another engineer merged changes into `main`
   recently (`move_picker.py`, attraction shots), so line numbers may have moved.

## Working rules
- You run in **your own git worktree**, on a new branch made from `wrap2`. Commit there in small logical commits.
  Commit subjects start with `feat:`, `fix:` or `chore:`. **No** `Co-Authored-By`, **no** "Generated with" lines.
  (Git cannot have both `wrap2` and `wrap2/x`, so branches are named `wrap2-<name>`.)
- **Never push**, never switch or modify other branches, and never run git commands in the main checkout (only your worktree).
- First setup, once, in your worktree root (PowerShell or cmd): create a junction so you do not run `npm install`:
  `cmd /c mklink /J node_modules <path of the main checkout>\node_modules`
  Use the system `python` for pytest (run from `src-tauri/src-python`). Only if you change Rust code:
  set `CARGO_TARGET_DIR` to `<main checkout>\src-tauri\target-agents\<yourname>` and run `cargo test` there once at the end.
- **Windows tool quirk:** the Bash tool mangles backslashes inside inline `python - <<EOF` snippets and `sed` programs. Any script that
  contains a backslash must be written to a file with the Write tool and then run. In Python source use `chr(92)` if you need one in a regex.
- **Never start the real app** and never run anything that moves the mouse or takes keyboard focus. To look at a screen use the headless
  browser harness: start `npx vite --host 127.0.0.1 --port <your port>` from your worktree (a separate port per engineer, given in your task),
  drive `.agents/scratch/overlay-check/index.html?...` with Playwright (`chromium.launch()` headless; `.agents/scratch/overlay-check/shoot.mjs`
  and `docs/DEVELOPER_GUIDE.md` section 3 show how; copy a script to the worktree root to run it, delete it afterwards).
  Stop your Vite when you finish. Tauri calls are mocked there (`window.__TAURI_INTERNALS__` in `index.html`; extend the mock if you need a reply).
- **Do not edit**: `src/locales/**` (the lead runs extract and writes the Japanese afterwards; just wrap strings in `t`...`` / `<Trans>`),
  `docs/**`, `.agents/CODEMAP.md`, `package.json`, lockfiles, `requirements*.txt`. Put what belongs in the code map in your report.
- Touch only the files in your ownership list unless a few lines elsewhere are needed to make the feature work (list them in the report).
  Nine other engineers own the rest. Keep diffs focused: no reformatting, no renaming, no drive-by rewrites.
- **Defaults must not change existing projects.** A project saved before your change must render and behave as before unless the task says otherwise.
- **Tests:** every behaviour change gets a test beside the code (Vitest for `src`, pytest for Python). Before you report run
  `npm run typecheck` and `npm test` (baseline at the branch point: tsc clean, 33 files / 289 tests passing) and the pytest files that cover what
  you touched. The whole Python suite takes minutes and the PC is shared by ten engineers: run it at most once, at the very end, with `-q -x`.
  If something fails that you did not cause, say so and show how you know.
- **Be honest.** Say what you verified and how, and what you could not verify (no GPU, not tried in the real app, no real Mapbox key...).
  Never write "done" for something you did not run. If the task is bigger than described, deliver the solid part and list the rest.

## Final report (your last message; under 500 words)
1. Branch name and the commit list (`git log --oneline wrap2..HEAD`).
2. Files touched, including any outside your ownership list and why.
3. Tests added and the results you saw (copy the summary lines).
4. Code-map notes: 6-12 lines for `.agents/CODEMAP.md` (what, where, non-obvious behaviour).
5. User-visible changes the lead must put in the manual (EN/JA) and the new UI strings you added (the lead will translate).
6. Open problems and anything you decided that the user should know.
