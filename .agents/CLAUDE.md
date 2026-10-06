# Navivi — agent guide

Navivi is a desktop app (Tauri v2) that turns waypoints / GPS tracks into narrated,
cinematic map-route travel videos. Three layers:

| Layer | Where | Role |
|---|---|---|
| Frontend | `src/` | React 19 + TS + Vite 7 + Tailwind v4. Map editor (Mapbox GL via react-map-gl), clip-sequence video editor (`features/editor`), render UI. |
| Shell | `src-tauri/src/lib.rs` | Thin Rust layer: spawns the Python sidecar, streams its logs as events, zip/unzip `.nvv`, gpsbabel, open-in-explorer. |
| Media pipeline | `src-tauri/src-python/` | Python CLI: GPS parse → TTS → subtitles → attraction clips (ComfyUI) → route render (pydeck + Playwright) → timeline/export (FFmpeg). |

This `.agents/` folder is shared with Antigravity. Only `CLAUDE.md`, `CODEMAP.md`, `TECH_STACK.md` and `scratch/overlay-check/` are in git (see `.gitignore`); the rest of `scratch/` and `archive/` stay local. See [Housekeeping](#housekeeping-agents).

## Working style

- Keep token use proportionate: spread effort over the task, and don't overthink small things. Removing a feature or a line needs no test
  to prove it is gone (a deleted line is gone); spend verification on behavior that can actually break.
- Screenshots of the user's screen are fine and need no warning. Prefer headless browsers, CDP or silent flags over scripts that
  inject keys or move the mouse, which can steal their input; keep any such script short.

## Commands

```bash
npm run tauri dev          # full app (Vite on 127.0.0.1:1420 + Rust build)
npm run dev                # frontend only (Tauri APIs unavailable in a plain browser)
npx tsc --noEmit           # type-check (was clean as of 2026-09-30)
npm test                   # Vitest (jsdom): sidecar client, timeline model, file naming, GPX helpers, history
npm run typecheck           # same as tsc --noEmit
npm run build              # tsc && vite build
npm run extract && npm run compile   # Lingui: after adding/changing UI strings
npm run build:setup        # our own setup exe in setup/dist (see CODEMAP "Custom setup program"); add -- --skip-app to repackage only
npm run build:installer    # older NSIS installer in src-tauri/target/release/bundle/nsis (see CODEMAP "Installer")

# Python (run from src-tauri/src-python, with the SYSTEM python — see gotchas)
cd src-tauri/src-python
python -m pytest -q                     # ~2 min, 614 tests
python -m pytest tests/test_subtitle.py -q
python main.py <job_config.json> <mode> [waypoint_index] [--force] [--no-llm]
python main.py full_pipeline <job_config.json> [output_dir] [--force]
python main.py render_timeline <timeline.json> [output_video]
```

pytest was fully green on 2026-10-05 (the earlier known failures in `test_introclip.py` and `test_route_brief.py` no longer fail).

E2E: `e2e/*.spec.ts` (Playwright) mocks `window.__TAURI_INTERNALS__`; there is no
`playwright.config.*` in the repo, so they need a running dev server and an ad-hoc config.
`test/` at the root holds older unittest-style tests of `main.py`.

## Frontend (`src/`)

- Entry: `main.tsx` → providers `ThemeProvider > I18nProvider > UIProvider > WorkspaceProvider` → `App.tsx`.
- Views (`hooks/useUI.tsx`): `currentView` = `title_screen | new_project | editor`; in editor,
  `editorMode` = `map` (Sidebar + MapArea) or timeline (`features/editor/EditorView`).
- **`hooks/useWorkspace.tsx`** is the state owner: waypoints, route segments, metadata, settings,
  timeline, dirty state, load/save. Extend it rather than adding parallel state. `useHistory.ts` = in-memory undo/redo.
- `services/fileSystem.ts` — project save/load, GPX generation, timeline manifest, route cache.
- `services/versionHistory.ts` — persistent snapshots in `<project>/.history/` (max 30).
- `services/ollamaApi.ts` — script/prompt generation via Ollama (`127.0.0.1:11434`) through `@tauri-apps/plugin-http`.
- `features/map|editor` — feature folders; `components/ui` — shared chrome (TitleBar, StatusBar, AppSettings, RenderOverlay…).
- `types/index.ts` — `Waypoint`, `ProjectSettings`, `ProjectMetadata`, `TimelineData` (segments + subtitle cues, defined in `features/editor/model.ts`).
- `config/constants.ts` — `appConfig`, `fileSystem` names, `mapDefaults`, default settings, map styles.
- Icons: import from `components/ui/icons.tsx` (lucide re-exports), not lucide directly.
- Accent colour: `navi` (= `--accent-base`, e.g. #4287f5) is the real accent for solid fills and accent text.
  The numbered scale is *not* darker-by-number: `navi-500`/`navi-600` are light tints (#88c5eb / #66abef), so white
  text on `bg-navi-500` looks disabled. Use `bg-navi` + `hover:brightness-110`; tints like `bg-navi/10` for washes.
  (RenderOverlay still uses navi-500 in places — the user approved that look, leave it unless asked.)
- Map editing is wired with window CustomEvents: `enter-draw-mode` / `enter-via-mode` / `exit-via-mode`
  ({ wpId } = the stop whose *outgoing leg* is edited), `select-anchor` ({ index } insert-after point),
  `open-context-menu`, `preview-finished`. Drawing is per-leg: `activeWaypointId` + `isDrawMode` in MapArea,
  UI in `DrawBar.tsx`. The WaypointEditor is hidden while drawing/adding.
- Global key handlers: register once (`[]` deps) and read state through a ref. Several window `keydown`
  listeners handle Escape; React flushes their setState between listeners, and a handler that re-subscribes
  on render gets removed mid-dispatch and silently misses the key (MapToolbar had exactly this bug).
- Map camera is **uncontrolled** (`initialViewState`); read/drive it through `mapRef` (`getBearing`, `easeTo`,
  `fitBounds`) and subscribe to map events for live values (see `MapCompass.tsx`). Don't reintroduce a
  `viewState` + `onMove` setState loop: it re-rendered all of MapArea every frame (perf fix 2026-09-30).
  The save thumbnail is a small canvas in a ref; don't push per-move data into workspace state.
- Toolbars: the user wants icon-only buttons with a hover tooltip (name + shortcut), not always-visible labels.
  Use `components/ui/Tip.tsx` inside a `group/tool relative` button. Selected tool/state = accent (`bg-navi text-white`
  or `bg-navi/10 text-navi`), never black. Floating bars/popovers are `rounded-xl` with `rounded-lg` buttons.
  Settings-style screens use the Section/Row pattern in `AppSettings.tsx` (label + description left, control right).
- Shared UI pieces: `Dialog.tsx` (+ `dialogButton`, `dialogInput`) for small modals; `menuItems.ts` →
  `openContextMenu(event, items)` for every right-click / "⋯" menu (rendered by `ContextMenu.tsx`; map menus are
  built in `features/map/hooks/useStopMenus.ts`); `Switch.tsx`; `Slider.tsx` (never a bare `<input type="range">`); `Checkbox.tsx`; `ComboBox.tsx`; `Tip.tsx`. Overlays inset `top-10` below the TitleBar.
- Tailwind pitfall: `duration-*` also sets `transition-duration`, and the default `transition-property` is `all`,
  so an element using `animate-in … duration-100` that is moved after mount will *slide* there. Add
  `transition-none` (ContextMenu had this: it slid in from its off-screen measuring spot).
- Lingui: some old msgids are kebab keys whose English text is wrong or missing (`project-name` → "Untitled
  Project", `hide-track`). When restyling, prefer plain-English msgids and check the en catalog.
- UI style the user likes (RenderOverlay, sidebar redesign 2026-09-30): quiet desktop-tool look — sentence-case
  labels (no ALL-CAPS tracking), zinc neutrals, hairline borders, `rounded-md/lg` (no pill buttons), 13px body /
  11px meta, one accent. They dislike Material-ish pills, WordPress-style lists and "AI-ish" sparkle panels.
- UI text is American English ("color", not "colour"). Changing a msgid drops its ja translation, so carry it over when you rename one.
- i18n: Lingui v6 macros (`t`, `<Trans>`), locales `en` (source) and `ja`. Catalogs in `src/locales/{en,ja}/messages.po`; compiled `.ts/.js/.mjs` are generated.
- Env: `.env` → `VITE_ORS_API_KEY` (OpenRouteService routing), `VITE_MAPBOX_TOKEN`.
- Window is frameless (`decorations: false`); the custom `TitleBar` handles drag/min/max/close.
- react-rnd windows (WaypointEditor, layers panel): **don't** put `animate-in` / transform classes on them — it fights rnd positioning.
- `@mapbox/mapbox-gl-draw` is still in package.json but intentionally unused (native DOM markers for anchors).

## Frontend ⇄ Python contract

Rust commands (`lib.rs`), called with `invoke(...)`:

- `run_python_blueprint({ action, payload })` → runs `python src-python/main.py <action> <payload>` and returns stdout.
  **Naming is misleading:** `action` is the job_config path (argv[1]) and `payload` is the mode (argv[2]).
  One tracked process at a time; a new call kills the previous one. `cancel_python_blueprint` kills it.
- `start_render({ configPath, force? })` → `main.py full_pipeline <config> [--force]`, streams
  `render-log` / `render-error` events per line, then `render-finish` = `Success | Failed | Cancelled`. `cancel_render` stops it.
- `export_video({ projectDir })` → `main.py render_timeline <projectDir>/timeline.json`, emits `render-complete`.
- `export_project_archive` / `unzip_project` (`.nvv` archives), `copy_asset_file`, `open_in_explorer`,
  `convert_gps_to_gpx` (needs `gpsbabel` on PATH), `wake_up_ollama`.
- Python always prints a JSON result to stdout — on failure too (`{"success": false, "error", "traceback"}`, exit 1).
  Keep that contract when adding modes; progress text goes to stderr.

Rust spawns `python` with cwd = `src-tauri/`, i.e. whatever `python` is first on PATH
(currently `C:\Python314`). The root `.venv` exists but lacks deps (no pytest) — don't rely on it.

## Project on disk

Workspace dir: `~/Documents/Navivi/Workspaces/<project_id>/`. A project is that folder; it opens from the folder and
`job_config.json` is its one project file (the app database is the source of truth for settings, versions and the route
cache; job_config.json is what Python reads). A `.nvv` is only a zip made on demand by "Export for sharing" (lean by
default, see CODEMAP), never kept in sync with the folder.

```
<project>/
  job_config.json  timeline.json  thumbnail.png  raw_track.gpx
  assets/{image,audio,subtitles,video/{route,attraction,user}}
  .navivi/         # generated bookkeeping: routecache.json narration_cues.json overview_narration.json
                   #   asset_manifest.json gpsdata/   (see services/projectfiles.py)
```
Map tiles are shared: `~/Documents/Navivi/Cache/tiles` (env `NAVIVI_CACHE_DIR` overrides). Folders from older versions are
tidied the first time they are opened (Rust `tidy_project_folder`), and Python readers fall back to the old root names.

## Python pipeline (`src-tauri/src-python/`)

- `main.py` — argv dispatcher only. Per-stage modes (`gps`, `map`, `residential`, `tts`, `tts-all`,
  `attraction-tts[-all]`, `attraction[-all]`, `attraction-finalize`, `intro`, `outro`, `subtitle[-all]`,
  `concat`, `mux`, `transition`, `overview-script`, `all`, default = overview) live in `services/cli/`.
  Also `get_furigana` (readings) and `extract_words` (whole words with readings from a script) for the pronunciation dictionary, both via `services/localization/japanese_words.py` (fugashi + UniDic, pykakasi as the fallback).
- `services/vdoprocessing/videopipeline/pipeline.py::run_full_pipeline` — the real 8-stage pipeline:
  GPS → TTS (+cues) → subtitles → attraction videos → route render → leg narration splits →
  optional subtitle burn → intro/outro → `build_timeline`. Each stage is a `*_step.py` in that package.
  Steps checkpoint their outputs; `--force` regenerates everything.
- `services/config/job_config.py` — `JobConfigManager` is a **process-wide singleton** (tests reset it in `conftest.py`).
- `services/tuning.py` — central hand-tuned constants (speeds, colors, timings, GPU cooldown, FFmpeg threads).
  Per-project overrides come from `job_config.json` `settings.*`; tuning.py holds fallback defaults only.
- Rendering: `pydeckrecorder/` (3D, deck.gl in headless Chromium via Playwright → frames → ffmpeg) and
  `spatial_renderer/` (legacy 2D overview/waypoint maps, mixin-composed `SpatialRenderer`). `mapfetcher/` = tiles, geometry, pacing, graphic overlays.
- AI/local servers (auto-started on demand, idle-watchdog stopped): Irodori TTS (`bin/Irodori-TTS-Server`, port 8088), Qwen3-TTS balanced voice (`bin/Qwen3-TTS`, port 8090, own venv) and Kokoro fast voice (`bin/Kokoro-TTS`, port 8089, own venv); the engine switch is in Settings > Voice,
  ComfyUI Wan2.2 image-to-video (`bin/ComfyUI`, port 8189 — not installed on this machine; falls back to
  the depth-parallax clip, `parallax_generator.py`), Ollama (11434). The pipeline stops TTS/ComfyUI between stages to free VRAM (8 GB-class GPU target).
- `bin/` (gitignored) also holds FFmpeg, GPSBabel, and an Ollama build.
- `services/logger/progress.py` — shared `tracker` for the single live "[mm:ss] [n/N] …" status line; use it rather than print().
  `tracker.stage()` = a new top-level stage, `tracker.show()`/`show_item()` = status inside it. `run_full_pipeline`
  must call `stage()` exactly `PIPELINE_STAGES` (7) times on every path — a skipped stage still announces itself
  (`tests/test_pipeline_stages.py`). The frontend's progress ring and stage list depend on it.
- Render log in the app: Rust streams stdout → `render-log`, stderr → `render-error`; both go through
  `src/utils/pipelineLog.ts`, which recreates the terminal's in-place behaviour (counter-only tracker updates fold
  into one row, ffmpeg `-stats` attaches to the current row, main.py's final JSON becomes one error row).
  `PipelineLogPanel.tsx` renders it (Simple / Details). If you add a stage or change a stage title, update
  `STAGE_MATCHERS` there and the status-pill mapping in RenderOverlay. `.agents/scratch/pipeline-log/run.mts`
  (`node run.mts`) replays a real log through the parser.
- Comment style: tagged notes like `# [NOTE] [TTS] …`, `# [HACK] [Animation] …`, and long "why" docstrings. Match it.

## Gotchas

- **Edit files directly with Edit/Write. Don't write regex "patch_*.py" scripts** — earlier agents did (see
  `archive/`) and it caused encoding corruption and half-applied patches (commits `3b1cc28`, `5cc2943`).
  Mojibake like `running Python worker  Eand` in `lib.rs` comments is leftover damage.
- Files contain Japanese text and em dashes; keep UTF-8 without introducing BOMs.
- `.gitignore` excludes `*.md` (so a new Markdown file isn't committed unless it is in `docs/`, `.agents/` or is the README, or is force-added), most of `.agents/`, `.github`, `data/`, and media under `src-python`.
- Empty tracked `fix_*.py` files sit at the repo root — leftovers; leave them unless asked.
- The dev server ignores `src-tauri/**` for HMR; Python changes take effect on the next spawn, Rust changes need a rebuild.
  `src-tauri/.taurignore` ignores all of `src-python/**` (plus data/logs), so edits or downloads there never restart `tauri dev`
  mid-render. If a Rust change is needed, restart the app yourself.

## Git

- Remote `origin` = github.com/mzxrq/navivi; `main` is default. Work lands via PRs from `chore/*`, `frontend/*`, `feature/*` branches.
- Commit subjects mostly `feat: …` / `fix: …`. Commit/push only when asked.
- No `Co-Authored-By` / Claude attribution lines in commits or PR descriptions (user request).

## Housekeeping (.agents/)

- `CODEMAP.md` — what each frontend file does and its non-obvious behaviour. The user wants lean source with few
  comments: put explanations there, not in code (a short line only for a real trap). Update it when files change.
- `CLAUDE.md` — this file. `.claude/CLAUDE.md` is a one-line `@../.agents/CLAUDE.md` import so Claude Code auto-loads it without a file in the repository root (it is in git; the rest of `.claude/` is local).
- `TECH_STACK.md` — library list (shared with Antigravity).
- `scratch/` — throwaway scripts/notes for the current task; clean up when done.
  - `scratch/overlay-check/` — reusable visual harness: mounts the real App in headless Chromium with a mocked
    `__TAURI_INTERNALS__` (incl. `window.__emit(event, payload)` for render events), opens RenderOverlay, and
    screenshots/measures it at several window sizes. URL params: `theme=light|dark`, `locale=en|ja`,
    `stops=demo` (6-stop Shirahama route with stop-by, mixed modes, media, via points), `render=0` (don't open the
    overlay). `sidebar.mjs` / `sidebar-states.mjs` capture the sidebar and its menus/edit states. Copy `shoot.mjs` to the repo root to run it (needs
    `@playwright/test` resolution), with a dev server on :1420. The user often already has `npm run tauri dev`
    running on 1420; reuse it instead of starting another Vite.
- Layout facts: TitleBar is `h-10` (`z-100000`, above the `z-99999` dialogs/settings so its menu isn't blurred under them) and StatusBar `h-7` (`z-9999`); the user wants TitleBar to stay on top.
  Full-window overlays should inset `top-10` / `bottom-7` (StatusBar only exists in the editor view).
  `short:` Tailwind variant (App.css) = `max-height: 760px`.
- `archive/old-patch-scripts/` — historical one-off patch scripts from earlier sessions. Reference only; safe to delete.
- Other agent defs: `.github/agents/navivi-version-history.agent.md` (version-history feature brief).
