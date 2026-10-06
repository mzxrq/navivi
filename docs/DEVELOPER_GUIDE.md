# Navivi developer guide

This guide is for people who work on Navivi: you, a teammate, or someone who picks the project up in a year.
It says what every part does, how to run it, how to fix the usual breakages, how to add things, and how to build the installer.

It is written to be read, not memorised. Use the contents list, jump to what you need.

> Companion documents
> - [`docs/FEATURES.md`](./FEATURES.md): the feature list as a user would describe it.
> - [`docs/BACKEND_GAPS.md`](./BACKEND_GAPS.md): things the Python side can do that no screen offers yet.
> - [`docs/tts-voices-api.md`](./tts-voices-api.md): the voice server's HTTP interface.
> - `.agents/CODEMAP.md` and `.agents/CLAUDE.md`: the long, very detailed notes the AI agents use. Good when you need the "why" behind a quirk.

---

## Contents

1. [Navivi in five minutes](#1-navivi-in-five-minutes)
2. [Set up your computer](#2-set-up-your-computer)
3. [Run it](#3-run-it)
4. [Map of the repository](#4-map-of-the-repository)
5. [Every feature, and where it lives](#5-every-feature-and-where-it-lives)
6. [The frontend, part by part](#6-the-frontend-part-by-part)
7. [The Rust shell, part by part](#7-the-rust-shell-part-by-part)
8. [The Python pipeline, part by part](#8-the-python-pipeline-part-by-part)
9. [How the main flows work](#9-how-the-main-flows-work)
10. [Data: what is saved where](#10-data-what-is-saved-where)
11. [Settings reference](#11-settings-reference)
12. [Recipes: how to change things](#12-recipes-how-to-change-things)
13. [Fixing things: symptoms, causes, cures](#13-fixing-things-symptoms-causes-cures)
14. [Tests and CI](#14-tests-and-ci)
15. [Build the installer](#15-build-the-installer)
16. [Release checklist](#16-release-checklist)
17. [Working with git](#17-working-with-git)
18. [Not done yet](#18-not-done-yet)
19. [Glossary](#19-glossary)

---

## 1. Navivi in five minutes

Navivi turns a route (a list of places, or a recorded GPS track) into a narrated, cinematic map-travel video.
You pick the stops, write or generate a short script for each, add photos or your own clips, press **Generate**,
review the result and export one video.

It is a desktop app built from three layers that talk to each other:

```
 ┌───────────────────────────────┐
 │  Frontend  (src/)             │  React 19 + TypeScript + Vite 7 + Tailwind v4.
 │  what you see and click       │  Map editor, timeline editor, settings, assistant chat.
 └───────────────┬───────────────┘
                 │  invoke("command", {...})  and events
 ┌───────────────▼───────────────┐
 │  Shell  (src-tauri/src/)      │  Rust, Tauri v2. Starts Python, keeps the SQLite database,
 │  thin, safe, fast             │  stores API keys, zips projects, installs the Python runtime.
 └───────────────┬───────────────┘
                 │  runs   python main.py <mode> ...   and reads its output
 ┌───────────────▼───────────────┐
 │  Pipeline  (src-tauri/        │  Python. GPS parsing, text-to-speech, subtitles, photo clips,
 │  src-python/)                 │  route animation (pydeck in headless Chromium), FFmpeg editing.
 └───────────────────────────────┘
```

Other programs Navivi starts on demand: **Ollama** (local AI for scripts, port 11434), three voice servers
(**Irodori** 8088, **Kokoro** 8089, **Qwen3** 8090) and **ComfyUI** (moving photo clips, port 8189).
They stop on their own when idle.

Three ideas explain most of the code:

1. **The project is a folder.** `job_config.json` in that folder is the single project file. The frontend writes it,
   the Python pipeline reads it. The app's database remembers *where* projects are and keeps settings, version history and caches.
2. **One Python call at a time.** The Rust shell tracks a single Python process. Starting a new one kills the old one
   (you will see "Process was cancelled"). Screens that call Python must not overlap. See [section 13](#13-fixing-things-symptoms-causes-cures).
3. **Every stage is checkpointed.** Pressing Generate on a finished project changes nothing: the pipeline only makes
   what is missing. To remake something, delete its files (the app does this for you in the Review step and the Generate dialog).

---

## 2. Set up your computer

You need a Windows 10/11 PC. Navivi is built and tested on Windows only.

| Tool | Version | Why | How to check |
|---|---|---|---|
| Node.js | **24** (18+ runs the app, but the Lingui CLI and CI use 24) | frontend, scripts | `node -v` |
| Rust | stable, MSVC toolchain | the shell and the setup program | `rustc -V` (should say `x86_64-pc-windows-msvc`) |
| Visual Studio Build Tools | 2022 or newer, with **Desktop development with C++** and a **Windows 10/11 SDK** | Rust needs a C++ linker. **Only developers need this**, not people who run the finished app | `where link.exe` in a "Developer Command Prompt" |
| Python | **3.12** or newer, on PATH (`python`) | runs the pipeline and the tests while developing | `python -V` |
| FFmpeg | any recent build with `libass` and `xfade` (gyan.dev "essentials" is what the installer bundles) | all video work | `ffmpeg -version` |
| WebView2 | included in Windows 11; Windows 10 may need it | Tauri's browser | Edge installed means yes |
| uv | latest | builds the voice engines' Python environments (only for working on the engines) | `uv --version` |
| Git | any | | |
| Ollama *(optional)* | latest | local AI for scripts | `ollama list` |
| An NVIDIA GPU *(optional)* | 8 GB+ | fast voices, moving photo clips | `nvidia-smi` |

**Keys.** Copy `.env.example` to `.env` in the repository root and fill in:

- `VITE_MAPBOX_TOKEN`: a Mapbox *public* token (starts with `pk.`). Needed for the map.
- `VITE_ORS_API_KEY`: an OpenRouteService key. Needed for driving and some walking routes.

Users of the installed app type these keys into Settings > API keys instead. They are saved with the project settings.

**Install dependencies once:**

```bash
npm install
cd src-tauri/src-python
pip install -r requirements.txt          # everything, including torch and diffusers (large)
# or, for tests only (what CI uses):
pip install -r requirements-test.txt
```

> **Which Python?** When you run the app from the repository, Rust runs whatever `python` is first on your PATH
> (not the `.venv` in the repository root, which has no dependencies). Install the requirements into *that* Python.

---

## 3. Run it

### The whole app (normal development)

```bash
npm run tauri dev
```

This starts Vite on `http://127.0.0.1:1420` (it insists on that port) and builds and opens the Rust shell.
The first build takes a few minutes. Afterwards:

| You change | What happens |
|---|---|
| a file in `src/` | hot reload in the window |
| a file in `src-tauri/src-python/` | nothing restarts (on purpose, so a running render is never killed). The next time Rust starts Python, the new code runs |
| a file in `src-tauri/src/` (Rust) | you must stop and rerun `npm run tauri dev` |
| `tauri.conf.json`, `Cargo.toml` | restart |

`src-tauri/.taurignore` is why Python edits never restart the app.

### Only the frontend (fast, but Tauri features are missing)

```bash
npm run dev          # http://127.0.0.1:1420 in a normal browser
```

Anything that calls Rust (`invoke`) does nothing here. Use it only for layout work. For a better preview use the
**browser harness** below.

### The browser harness (look at screens without the real app)

`.agents/scratch/overlay-check/` mounts the real `App` in headless Chromium with a fake Tauri. It is how the screenshots in the
user manual were taken. With the dev server running:

```
http://127.0.0.1:1420/.agents/scratch/overlay-check/index.html?theme=light&locale=en&stops=demo&render=0
```

Useful parameters: `theme=light|dark`, `locale=en|ja`, `stops=demo` (a six-stop Shirahama route), `render=0` (do not open the
render overlay), `view=title` or `view=new`, `editor=demo` (a timeline), `review=demo`, `assets=demo`, `ai=1`, `projcfg=1`.
The harness is in git (`.agents/scratch/overlay-check/`); the rest of `.agents/scratch/` is local scratch space.

### The Python pipeline on its own

Run from `src-tauri/src-python` with the same `python` the app uses:

```bash
python main.py full_pipeline path/to/job_config.json [output_dir] [--force]   # the whole pipeline
python main.py render_timeline path/to/timeline.json [output_video]           # export from a timeline
python main.py path/to/job_config.json tts-all                                # one stage (see section 8)
python main.py estimate path/to/job_config.json                               # render time estimate (JSON)
python main.py system_info                                                    # RAM, CPU count (JSON)
```

Every mode prints one JSON object as its **last stdout line**, on failure too (`{"success": false, "error": ..., "traceback": ...}`
and exit code 1). Progress text goes to stderr. Keep that contract when you add a mode; the frontend parses it.

### Useful folders while developing

| What | Where |
|---|---|
| Your projects | `Documents\Navivi\Workspaces\<project>\` |
| The app database | `%APPDATA%\navivi\navivi.db` (SQLite) |
| Downloaded engines and recorded voices (dev) | `src-tauri\src-python\bin\` (git-ignored) |
| Shared map tiles | `Documents\Navivi\Cache\tiles` |
| Spoken-line cache | `Documents\Navivi\Cache\tts` |
| Photos you dropped in or the finder downloaded | `Documents\Navivi\Imports\` |
| Your music library | `Documents\Navivi\Music\` |
| Python log | `src-tauri\src-python\services\logger\app.log` (set `NAVIVI_LOG_FILE` to move it) |

### Environment variables

| Variable | Meaning |
|---|---|
| `VITE_MAPBOX_TOKEN`, `VITE_ORS_API_KEY` | frontend keys, read from `.env` at build time |
| `NAVIVI_BIN_DIR` | where engines (Kokoro, Qwen3, Irodori, ComfyUI), recorded voices and Ollama live. Set by Rust for an installed app |
| `NAVIVI_TOOLS_DIR` | the installer's `tools/` folder (ffmpeg, gpsbabel, uv) |
| `NAVIVI_UV` | path to `uv.exe` |
| `NAVIVI_CACHE_DIR` | moves the shared cache (tiles, spoken lines) |
| `NAVIVI_LOG_FILE` | moves the Python log (the test suite does this) |
| `NAVIVI_TTS_DEVICE` | force the voice device (`cpu` / `cuda`) |
| `NAVIVI_AI_KEY_<PROVIDER>` | online AI keys, handed to Python by Rust. Never written to a file |
| `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` | e.g. `--remote-debugging-port=9333` to drive the installed app with Playwright |

---

## 4. Map of the repository

```
navivi/
├─ src/                      the frontend (React + TypeScript)
│  ├─ main.tsx               entry: providers, error boundary, splash handoff
│  ├─ App.tsx                chooses the screen (project list, new project, editor)
│  ├─ components/ui/         shared chrome and dialogs (title bar, settings, render overlay, ...)
│  ├─ components/view/       the two full screens: ProjectManager, ProjectSettingsModal
│  ├─ features/map/          the map editor
│  ├─ features/editor/       the timeline editor
│  ├─ features/assistant/    the AI chat
│  ├─ hooks/                 state owners (workspace, UI, assistant) and small helpers
│  ├─ services/              talking to the outside: Python, files, database, AI, geocoding, photos
│  ├─ utils/                 small pure helpers (almost all unit-tested)
│  ├─ config/                constants, map styles, transitions, credits
│  ├─ types/                 TypeScript types (Waypoint, ProjectSettings, ...)
│  └─ locales/               English and Japanese strings (Lingui .po files)
├─ src-tauri/
│  ├─ src/                   the Rust shell (see section 7)
│  ├─ src-python/            the Python pipeline (see section 8)
│  ├─ capabilities/          what the webview is allowed to do (files, http, dialogs)
│  ├─ installer/             the old NSIS installer template and its pictures
│  ├─ tauri.conf.json        windows (main + splash), app id, version
│  └─ tauri.installer.conf.json   extra config for the NSIS build
├─ setup/                    our own small installer program (Rust + WebView2), see section 15
├─ scripts/                  build helpers: build-setup, stage-installer, make-installer-art, stock-voices.json
├─ docs/                     the documents you are reading (the only .md files git keeps, besides README)
├─ e2e/                      Playwright specs (need a running dev server and an ad-hoc config)
├─ public/ splash.html       static files, the logo, the splash window page
├─ .github/workflows/ci.yml  the checks that run on every pull request
├─ .agents/                  notes for AI agents (CLAUDE.md, CODEMAP.md, TECH_STACK.md) and the browser harness
├─ .claude/CLAUDE.md         one line that makes Claude Code load .agents/CLAUDE.md (no file in the repository root)
└─ README.md  package.json  vite.config.ts  vitest.config.ts  lingui.config.ts  tsconfig*.json
```

Git ignores `*.md` (except `README.md`, `docs/*.md` and `.agents/*.md`), most of `.agents/scratch`, most of `.github`, `data/`, and big media under
`src-python`. If a new Markdown file does not show up in `git status`, that is why: `git add -f` it, or put it in `docs/`.

---

## 5. Every feature, and where it lives

Read this as "if a user says *X* is broken, open *these* files". "Py" means `src-tauri/src-python/services/...`.

### Projects and files

| Feature | Frontend | Rust | Python |
|---|---|---|---|
| Project list: grid or table, search, rename, duplicate, remove, reveal in Explorer, quick render | `components/view/ProjectManager.tsx`, `services/projectStore.ts` | `db/projects.rs`, `project_files.rs` (duplicate) | |
| New project form (name, start from blank / GPS track, starting point, travel mode, export ratio, title card, fast render) | `components/ui/NewProject.tsx` | | |
| Save, Save As, autosave, unsaved-changes dialog | `hooks/useWorkspace.tsx`, `hooks/useAutoSave.ts`, `services/fileSystem.ts`, `components/ui/SaveAs.tsx`, `UnsavedChanges.tsx` | | |
| Version history (30 snapshots per project) | `services/versionHistory.ts`, status bar History popup | `db/versions.rs` | |
| Project settings dialog (route marker, animate photos, timing cues, fade) | `components/view/ProjectSettingsModal.tsx` | | |
| Export for sharing (`.nvv` zip, lean or complete), open a shared `.nvv` | `components/ui/ExportProjectDialog.tsx` | `project_files.rs` (`export_project_archive`), `lib.rs` (`unzip_project`) | |
| Old folders tidied on first open | `services/fileSystem.ts` (`tidyProjectFolder`) | `project_files.rs` (`tidy_project_folder`) | `services/projectfiles.py` |
| Undo / redo (maps and timeline separately) | `hooks/useHistory.ts` | | |

### Planning the route (map editor)

| Feature | Frontend | Notes |
|---|---|---|
| 3D map, styles, layers panel, compass, 3D terrain | `features/map/components/MapArea.tsx`, `MapLayers/*`, `MapCompass.tsx`, `config/constants.ts` | Mapbox GL via react-map-gl. Camera is "uncontrolled": drive it through `mapRef` |
| Add, move, reorder, rename, delete, duplicate stops; stop vs stop-by; return stops | `Sidebar.tsx`, `WaypointItem.tsx`, `hooks/useWaypointActions.ts`, `features/map/hooks/useStopMenus.ts` | |
| Travel mode per leg (walk, drive, ferry, fly, direct, draw) and routing | `features/map/hooks/useMapRouting.tsx`, `utils/routeCacheKey.ts`, `utils/gsiPaths.ts` | OpenRouteService / OSRM; GSI path data fills gaps in Japan |
| Via points | `useStopMenus.ts`, `MapArea.tsx` events `enter-via-mode` / `exit-via-mode` | |
| Draw a leg by hand | `DrawBar.tsx`, `DrawControl.tsx`, `MapArea.tsx` | |
| Leg colours, elevation heatmap and profile | `LegColorButton.tsx`, `ElevationProfile.tsx`, `RouteLayer.tsx` | |
| Location search | `components/ui/LocationSearch.tsx` | |
| Import GPX / FIT / TCX / KML; drop photos with GPS | `hooks/useFileActions.ts`, `utils/gpxTrack.ts` | Py: `gpsparser/`, CLI `import_gps_track` (gpsbabel converts other formats) |
| HEIC photo conversion | `services/imageImport.ts` | Py: `services/imageconvert.py` |
| Context menus on everything | `components/ui/ContextMenu.tsx`, `menuItems.ts` | |

### Stops: scripts, photos, videos

| Feature | Frontend | Python |
|---|---|---|
| Stop editor window (name, stop/stop-by, pause, skip in video, marker) | `features/map/components/WaypointEditor.tsx` | |
| Two scripts per stop (arriving, attraction), character counter, Ctrl+Enter save | `components/ui/ScriptInput.tsx` | |
| Auto-Write with a local or online AI | `services/ollamaApi.ts`, `services/narrationPrompt.ts`, `services/ai/*` | |
| Auto-Director (read a document, fill in stops) | `components/ui/AutoDirectorModal.tsx` | |
| Pronunciation dictionary (project and shared), kanji scan | `ScriptInput.tsx`, `AppSettings.tsx` (Pronunciation tab) | `localization/japanese_words.py`, CLI `get_furigana`, `extract_words` |
| Photos per stop (up to 3) with camera angle; own videos (up to 3) | `WaypointEditor.tsx`, `WaypointVideos.tsx` | `vdoprocessing/img2vdo.py`, `user_videos.py` |
| Find free photos online (Wikimedia) with credits | `services/placePhotos.ts`, `utils/photoCredits.ts`, Photos tab, assistant checkbox | |
| Intro title card text | `features/map/components/OverviewPanel.tsx`, timeline Inspector | `vdoprocessing/introclip.py`, `videopipeline/intro_step.py` |

### The AI assistant

| Feature | Where |
|---|---|
| Chat on the start screen and in the editor; attach PDF, Word, text, web page, GPX, photos | `features/assistant/AssistantChat.tsx`, `AssistantPanel.tsx`, `hooks/useAssistant.tsx`, `services/assistant/sources.ts` (Py: `services/documents.py`, CLI `read_document`) |
| Brief (what the user wants) and replies | `services/assistant/brief.ts`, `converse.ts` |
| Build a project (find places, geocode, photos, scripts) | `services/assistant/buildProject.ts`, `services/geocode.ts` |
| Chat saved in the project | `services/assistant/chatStore.ts` (`<project>/assistant.json`) |
| Providers: Ollama, OpenRouter (sign-in), Anthropic, OpenAI, Gemini, any OpenAI-compatible server | `services/ai/providers.ts`, `online.ts`, `openrouterAuth.ts`, `components/ui/OnlineAiSettings.tsx`; Rust `oauth.rs`, `secrets.rs` |

### Voices and subtitles

| Feature | Frontend | Python |
|---|---|---|
| Three voice engines (Natural = Irodori, Balanced = Qwen3, Fast = Kokoro), voice library, cloning, preview, speed | `components/ui/VoiceSettings.tsx` | `services/tts/*`, `services/cli/voice_commands.py`, `tts_commands.py` |
| Set up an engine with one button | `components/ui/ComponentsChecklist.tsx` (Settings > Setup) | `services/tts/{kokoro,qwen3,irodori}_setup.py` |
| Subtitles from narration; look (font, size, colour, box, opacity) | `AppSettings.tsx` (Video tab), `components/ui/Caption*.tsx`, `SubtitleSample.tsx`, `utils/subtitleLook.ts` | `localization/subtitle.py`, `caption_box.py`, `fonts.py`, `google_fonts.py` |
| Google Fonts download | `components/ui/FontDownloadDialog.tsx` | CLI `google_fonts_catalog`, `install_google_font` |

### Generating and reviewing

| Feature | Frontend | Python |
|---|---|---|
| Generate dialog (summary, estimate, existing-assets list) | `features/map/components/GenerateDialog.tsx`, `services/assetCleanup.ts`, `hooks/useRenderEstimate.ts` | `services/render_estimate.py`, CLI `estimate` |
| Progress window, live log | `components/ui/RenderOverlay.tsx`, `PipelineLogPanel.tsx`, `utils/pipelineLog.ts` | `services/logger/progress.py`, `videopipeline/pipeline.py` |
| Review step (redo clip / redo voice, edit text, fix pronunciation) | `components/ui/ReviewStep.tsx` | |
| Route animation (3D, pydeck in headless Chromium) | | `vdoprocessing/route2vdo.py`, `pydeckrecorder/*`, `videopipeline/render_step.py` |
| Photo clips (moving: ComfyUI Wan 2.2 / LTX-Video; fallback: a depth-parallax move over the photo) | | `vdoprocessing/img2vdo.py`, `comfyui_i2v_client.py`, `ltx_keyframed.py`, `parallax_generator.py` (the fallback), `slow_move.py`, `shot_builder.py` |
| Intro and outro cards | | `introclip.py`, `outrocard.py` |

### Timeline editor and export

| Feature | Where |
|---|---|
| Clip sequence, trim, reorder, narration offset, volume, mute, fades | `features/editor/EditorView.tsx`, `TimelinePane.tsx`, `Inspector.tsx`, `model.ts` |
| Preview player | `features/editor/Preview.tsx`, `player.ts` |
| Subtitles lane (add, drag, multi-select, import `.srt`, save `.srt`) | `TimelinePane.tsx`, `EditorView.tsx`, `utils/srtParser.ts` |
| Music picker (your folder, optional `library.json`) | `features/editor/MusicPicker.tsx` |
| Auto edit | `model.ts` (`autoArrange`) |
| Export | `features/editor/ExportDialog.tsx` → Rust `export_video` → Py `render_timeline` → `vdoprocessing/vdoexporter.py` |

### App-level

| Feature | Where |
|---|---|
| Frameless window, menu, undo/redo, map/timeline switch | `components/ui/TitleBar.tsx` |
| Status bar (stats, saved state, History, System log) | `components/ui/StatusBar.tsx` |
| Splash window and reveal | `splash.html`, `utils/splash.ts`, Rust `app_ready` |
| First-run setup dialog (installed app only) | `components/ui/SetupGate.tsx`, `services/setup.ts`; Rust `runtime.rs` |
| Settings (General, Appearance, API keys, Video, Voice, Pronunciation, AI models, Setup, About) | `components/ui/AppSettings.tsx`, `AboutPanel.tsx`, `VoiceSettings.tsx`, `OnlineAiSettings.tsx`, `ComponentsChecklist.tsx` |
| English and Japanese UI | `src/i18n.ts`, `src/locales/*`, Lingui macros |
| Toasts, error screen | `components/ui/Toast.tsx`, `ErrorBoundary.tsx` |

---

## 6. The frontend, part by part

### 6.1 Providers and where state lives

`main.tsx` wraps the app in this order (outer to inner):
`ThemeProvider` > `I18nProvider` > `UIProvider` > `WorkspaceProvider` > `AssistantProvider` > `ErrorBoundary` > `App`.

| Owner | What it holds |
|---|---|
| `hooks/useUI.tsx` | which screen (`currentView`: `title_screen`, `new_project`, `editor`), editor mode (`map` or timeline), toasts, whether a render is running, settings dialog open |
| `hooks/useWorkspace.tsx` | **the project**: stops, route segments, metadata, settings, timeline, dirty flag, load, save, versions, undo/redo. Extend this, do not add parallel state |
| `hooks/useAssistant.tsx` | chat messages, the brief, attached sources, build progress, per-project chat saving |
| `hooks/useTheme.tsx` | light / dark / system, accent colour |

The AI choices (`ai_provider`, model, keys' names, ...) are **app-wide**, stored in the database under the app setting `ai_settings`,
and merged over the project's settings. A project file cannot switch them.

### 6.2 Talking to the outside (`src/services/`)

| File | Purpose |
|---|---|
| `sidecar.ts` | the only place that calls the Python sidecar. `callSidecar(mode, input)` never throws; `callSidecarShared` joins identical in-flight calls; `runStage(configPath, mode)` runs a pipeline stage |
| `fileSystem.ts` | save and load a project, GPX generation, timeline manifest, route cache, folder tidying. **Contains the waypoint serializer** (see recipe 12.1) |
| `db.ts` | typed wrappers over the Rust database commands (projects, settings, versions, route cache, app settings) |
| `projectStore.ts`, `versionHistory.ts` | project list and version snapshots on top of `db.ts` |
| `ollamaApi.ts` | Ollama requests (script streaming, model list, pull, warm-up) |
| `ai/*` | online AI providers, key storage, photo shrinking, OpenRouter sign-in |
| `assistant/*` | the chat brain, document reading, project builder, chat file |
| `geocode.ts` | place name → coordinates, kept inside the right region |
| `placePhotos.ts` | free photos from Wikimedia |
| `imageImport.ts` | photo import (HEIC → JPEG) |
| `assetCleanup.ts` | count and delete generated files by group |
| `renderEstimate.ts`, `setup.ts` | estimate and first-run setup helpers |

### 6.3 Conventions worth knowing

- **Icons** come from `components/ui/icons.tsx` (lucide re-exports). Never import `lucide-react` directly.
- **Accent colour.** `navi` (= `--accent-base`) is the real accent. The numbered scale (`navi-500`) is *not* darker by number; use `bg-navi hover:brightness-110`.
- **Look.** Quiet desktop style: sentence-case labels, zinc neutrals, hairline borders, `rounded-md/lg`, 13 px body, one accent. No all-caps tracking, no pills, no `font-mono`.
- **Toolbars** use icon-only buttons with the `Tip` hover label. Menus use `openContextMenu`. Small modals use `Dialog`. Sliders use `Slider`, never a bare range input.
- **Text** is American English ("color"). Every user-visible string goes through Lingui (`t`...`` or `<Trans>`).
- **Global key handlers** are registered once with `[]` dependencies and read state from a ref. A handler that re-subscribes on render can be removed in the middle of a key event and miss it.
- **Windows events.** Map editing is wired with `window` custom events: `enter-draw-mode`, `enter-via-mode`, `exit-via-mode`, `select-anchor`, `open-context-menu`, `focus-waypoint`, `project-saved`, `export-project`, `open-app-settings-tab`.
- **react-rnd windows** (the stop editor, layers panel): never put `animate-in` or transform classes on them.
- **Lean source.** Explanations belong in `.agents/CODEMAP.md` or this guide, not in long code comments. A short line is fine for a real trap.

---

## 7. The Rust shell, part by part

All in `src-tauri/src/`. It is small on purpose.

| File | Job |
|---|---|
| `main.rs`, `lib.rs` | window setup, the splash handoff, starting and killing Python, and most commands below |
| `runtime.rs` | decides where Python, tools and engines live (repository vs installed app) and installs the pipeline's Python on first run |
| `project_files.rs` | zip a project for sharing, copy a project (Duplicate), tidy an old folder |
| `secrets.rs` | API keys in the Windows Credential Manager (`keyring`). Names must be `ai-key:<provider>` |
| `oauth.rs` | the loopback listener for the OpenRouter sign-in |
| `db/` | SQLite: `projects`, `project_settings`, `project_versions`, `route_cache`, `app_settings`; migrations in `migrations.rs` |

### Commands the frontend can call

| Command | What it does |
|---|---|
| `run_python_blueprint({action, payload})` | run `main.py <action> <payload>`, return stdout. **Misleading names:** `action` is argv[1] (a mode name *or* a job_config path), `payload` is argv[2]. One call at a time; a new call kills the previous one |
| `cancel_python_blueprint` | kill the running call |
| `start_render({configPath, force?})` | run `main.py full_pipeline`, stream every line as `render-log` / `render-error`, then `render-finish` = `Success`, `Failed` or `Cancelled` |
| `cancel_render` | stop it |
| `export_video({projectDir})` | run `main.py render_timeline`, emit `render-complete`, return the video path |
| `runtime_status`, `runtime_install` | check and create the pipeline's Python (installed app); stream `setup-step` / `setup-log` |
| `export_project_archive`, `unzip_project`, `duplicate_project_folder`, `tidy_project_folder` | project archives and folders |
| `copy_asset_file`, `open_in_explorer`, `convert_gps_to_gpx` | small file helpers (the last needs `gpsbabel`) |
| `secret_set`, `secret_get`, `secret_delete` | API keys |
| `oauth_listen_start`, `oauth_listen_wait`, `oauth_listen_cancel` | sign-in redirect |
| `wake_up_ollama` | start Ollama if it is installed |
| `app_ready` | called by the frontend after its first render; closes the splash |
| `project_*`, `settings_*`, `version_*`, `route_cache_*`, `app_setting_*` | the database |

The database lives in `%APPDATA%\navivi\navivi.db`. To start fresh, close the app and delete that file (projects on disk are not touched, but the project list and
version history are lost).

Adding a command: see recipe 12.5.

---

## 8. The Python pipeline, part by part

Everything is in `src-tauri/src-python/`. `main.py` is only a dispatcher; the work is in `services/`.

### 8.1 The command line (`main.py`)

Modes that take a **job_config path first**, then the mode (this is how `runStage` calls them):

| Mode | What it does |
|---|---|
| `gps` | parse the GPS source into a cleaned route |
| `upscale-images` | upscale stop photos |
| `map`, `residential` | render the overview map video / the per-leg ("residential") videos |
| `tts [n]`, `tts-all`, `overview-tts`, `attraction-tts [n]`, `attraction-tts-all` | speak the script of one stop (`n`, default 0) or of every stop. A multi-word payload such as `"tts 3 --force"` is split by main.py |
| `attraction`, `attraction-all`, `attraction-finalize` | make the photo clips; finalize combines multi-photo clips |
| `intro`, `outro` | title and ending cards |
| `subtitle`, `subtitle-all` | subtitles from narration |
| `concat`, `mux`, `transition` | stitch clips, add audio, add transitions |
| `overview-script` | write the overview narration with the chosen AI |
| `all` | every stage in order. Default (no mode) renders the overview |

Utility modes (**mode name first**, JSON payload second):

| Mode | What it does |
|---|---|
| `full_pipeline <config> [dir] [--force]` | the real pipeline (section 8.2) |
| `render_timeline <timeline.json> [out]` | the export |
| `estimate <config>` | JSON render-time estimate |
| `system_info` | RAM and CPU facts |
| `get_furigana`, `extract_words` | readings for the pronunciation dictionary |
| `read_document` | text from a PDF / Word / text file |
| `import_gps_track` | convert and parse a track file |
| `convert_images` | HEIC to JPEG |
| `google_fonts_catalog`, `install_google_font`, `list_fonts` | fonts |
| `tts_voices_list`, `tts_voice_add`, `tts_voice_delete`, `tts_voice_preview`, `tts_engines` | voice library and engine status |
| `tts_install_kokoro`, `tts_install_qwen3`, `tts_install_irodori`, `comfyui_install` | install an engine |

Flags: `--force` regenerates; `--no-llm` skips AI writing. (Check `main.py` for the current list: it is the source of truth.)

### 8.2 The pipeline (`vdoprocessing/videopipeline/pipeline.py`)

`run_full_pipeline` makes **exactly seven announced stages** (`PIPELINE_STAGES = 7`), even when a stage is skipped. The frontend's progress ring and
stage list depend on that count (`tests/test_pipeline_stages.py`).

| # | Stage | Step module | Output |
|---|---|---|---|
| 1 | Parsing GPS track | `gps_step.py` | cleaned route |
| 2 | Generating TTS narration (+ narration cues) | `audio_step.py`, `narration_step.py` | `assets/audio/*.wav` |
| 3 | Generating subtitles | `subtitle_step.py` | `assets/subtitles/*.srt` |
| 4 | Upscaling waypoint photos | `upscale_step.py` | upscaled copies (original paths are restored in job_config) |
| 5 | Generating attraction videos | `attraction_step.py` | `assets/video/attraction/*.mp4` |
| 6 | Rendering overview and leg videos | `render_step.py`, `leg_pieces.py` | `assets/video/route/*.mp4` |
| 7 | Building intro and outro clips (then the timeline) | `intro_step.py`, `outro_step.py`, `timeline_step.py` | `assets/video/00_intro.mp4`, ..., `timeline.json` |

If you add or rename a stage, update `STAGE_MATCHERS` in `src/utils/pipelineLog.ts` and the status-pill mapping in `RenderOverlay.tsx`.

### 8.3 The packages

| Package | What is in it |
|---|---|
| `services/cli/` | the mode handlers called by `main.py` (gps, tts, voice, attraction, combine, subtitle, intro/outro, image, system) |
| `services/config/` | `job_config.py` (`JobConfigManager`, a process-wide singleton: tests reset it in `conftest.py`), `upscaled_images.py` |
| `services/gpsparser/` | GPX/FIT/TCX/KML reading, distance maths, stay detection |
| `services/mapfetcher/` | map tiles, geometry, pacing (how fast the camera moves), languages, and `graphicengine/` (popups, cards, icons, sprites drawn onto frames) |
| `services/vdoprocessing/` | everything video: route renderers (`route2vdo.py`, `pydeckrecorder/`, `spatial_renderer/`), photo-clip generators, intro/outro cards, the exporter and editor (FFmpeg), the step modules |
| `services/model/` | legacy image-to-motion models (classic pan, depth parallax, outpainting). Nothing imports this package any more; see BACKEND_GAPS.md section 5 |
| `services/tts/` | voice engines (`ttsengine.py`), the three servers, setup modules, voice library, spoken-line cache, artifact cleaning |
| `services/localization/` | script writing (local and online), overview narration, subtitles, fonts, Japanese readings, text styles |
| `services/logger/` | the logger and `progress.py`, the shared `tracker` that prints the live "[mm:ss] [n/N] ..." line. Use it instead of `print()` |
| `services/tuning.py` | **every hand-tuned constant** (speeds, colours, timings, ports, quality presets, FFmpeg threads, GPU cooldown). Project settings override these; tuning holds the fallbacks |
| `services/runtime_paths.py` | the one place that knows where `bin`, engines, FFmpeg, GPSBabel and uv are. Nothing else builds a path to `bin` |
| `services/render_estimate.py` | time estimate that learns from the last runs (`Documents\Navivi\render_timings.json`) |
| `services/projectfiles.py` | where generated bookkeeping files live inside a project |

### 8.4 Servers Python starts on demand

| Server | Port | Where | Stops |
|---|---|---|---|
| Irodori TTS (Natural voice) | 8088 | `bin/Irodori-TTS-Server` | idle watchdog |
| Kokoro TTS (Fast voice) | 8089 | `bin/Kokoro-TTS` | exits itself after 600 s idle |
| Qwen3 TTS (Balanced voice) | 8090 | `bin/Qwen3-TTS` | exits itself when idle |
| ComfyUI (moving photo clips) | 8189 | `bin/ComfyUI` | idle watchdog; the pipeline also stops it between stages |
| Ollama (local AI) | 11434 | its own install | not managed by us |

Each engine has its own virtual environment (different Python and package versions), a `.ready` file written by its setup module, and a pid file.
The pipeline stops the voice servers and ComfyUI between stages to free graphics memory (the design target is an 8 GB card).

---

## 9. How the main flows work

### 9.1 Opening and saving a project

```
open  → loadProjectData (fileSystem.ts) reads job_config.json, makes paths absolute
      → useWorkspace.loadProject maps it to React state   ← the "loader map" (recipe 12.1)
      → tidyProjectFolder (once), syncProjectOnOpen (database), version list, timeline load
save  → saveProjectData writes job_config.json, copies photos/videos into assets/,
        writes thumbnail.png, raw_track.gpx; upserts the database row
      → saveTimelineManifest writes timeline.json
      → fires window event "project-saved" (the assistant moves its chat file along)
```

### 9.2 Generate

```
GenerateDialog → save project → (optional: delete ticked asset groups)
 → start_render → Python full_pipeline  → render-log lines → RenderOverlay / PipelineLogPanel
 → render-finish "Success" → buildReviewRows → ReviewStep  (or, with Quick export, straight to export)
 → Accept → export_video → timeline.json → VideoExporter → final .mp4
```

Quick export skips the review. Fast render skips voices and photo clips.

### 9.3 The assistant builds a project

```
user message → converse() (AI) → brief updated → "Create project" appears
Create project → buildProject:
   1 places   (from the brief or read from the attached document by the AI)
   2 geocode  (Mapbox / OSM, inside a box so namesakes far away are ignored)
   3 photos   (optional: Wikimedia Commons; downloads to Documents\Navivi\Imports)
   4 scripts  (arriving + attraction script per stop, with facts from OpenStreetMap)
 → editor opens with the stops; chat is saved into the project on its first save
```

### 9.4 Voice

`ttsengine.make_tts_client(settings, output_dir)` is the one place a voice client is made. Lines are chunked, spoken by the chosen engine's server,
cleaned (`artifacts.remove_stray_bursts` removes a rare stray "あ" burst), and cached by request (`phrase_cache.py`, 500 MB). The voice
fingerprint includes the engine, so changing engine marks finished narration out of date.

### 9.5 Online photos and credits

`placePhotos.findPlacePhotos` asks Wikipedia (article lead image near the stop) and Commons (files within 120 m, files named like the stop),
keeps only photos with free licenses, one request at a time with a proper `User-Agent`. `downloadPhotos` saves 1920 px copies. The credit (author, license, page)
is stored per photo in `Waypoint.imageCredits`, shown under the photo and listed in the export dialog.

---

## 10. Data: what is saved where

### A project folder

```
<project>/
  job_config.json     the project: stops, scripts, settings. The one project file
  timeline.json       the clip sequence and subtitles (also read by the exporter)
  assistant.json      the assistant chat for this project
  thumbnail.png       card image in the project list
  raw_track.gpx       the route as a GPX file
  assets/
    image/            your photos (and map frames if enabled)
    audio/            narration .wav, music in audio/music
    subtitles/        .srt files
    video/            00_intro.mp4 ...; route/ attraction/ user/
  .navivi/            generated bookkeeping, safe to delete: routecache.json, narration_cues.json,
                      overview_narration.json, asset_manifest.json, gpsdata/
```

`.navivi/` is rebuildable. `assistant.json` is not, which is why it sits in the root. A shared `.nvv` is just a zip of this folder
(lean: without rendered clips and caches; complete: with them).

### On the PC

| Where | What |
|---|---|
| `Documents\Navivi\Workspaces\` | projects |
| `Documents\Navivi\Cache\tiles`, `Cache\tts` | shared caches (safe to delete) |
| `Documents\Navivi\Imports\` | files you dropped in, photos the finder downloaded |
| `Documents\Navivi\Music\` | your music library |
| `Documents\Navivi\render_timings.json` | learned render times |
| `%APPDATA%\navivi\navivi.db` | the database |
| `%LOCALAPPDATA%\navivi\runtime\venv` | the pipeline's Python (installed app) |
| `%LOCALAPPDATA%\navivi\bin` | engines (Kokoro, Qwen3, Irodori, ComfyUI), recorded voices |
| Windows Credential Manager, service "Navivi" | online AI keys |
| `<install folder>\navivi.exe`, `src-python\`, `tools\` | the installed app (read-only) |

### The database

| Table | Holds |
|---|---|
| `projects` | id, name, folder, status, thumbnail, last opened, soft-delete flag |
| `project_settings` | the project's settings as JSON (what the app reads when it opens the project) |
| `project_versions` | up to 30 saved snapshots per project |
| `route_cache` | routed legs, keyed by from, to, mode and the drawn-path hash (plus the via-point hash when there are via points) |
| `app_settings` | app-wide values: `ai_settings`, the shared pronunciation dictionary, `firstRunChecklistDone`, ... |

---

## 11. Settings reference

`ProjectSettings` is defined in `src/types/index.ts`; defaults are in `src/config/constants.ts`. The Python side reads them from `job_config.json` under `settings`.
Important: **the database copy wins when the app opens a project**, so a project setting edited only in the file is silently overridden. Change both, or change it through the app.

| Where it is edited | Settings |
|---|---|
| Settings > General | language, auto-save interval, AI features on/off, fast render (project) |
| Settings > Appearance | theme, accent colour, route marker, elevation heatmap |
| Settings > API keys | Mapbox token, OpenRouteService key |
| Settings > Video | frames per second, quick export, hardware mode, subtitle look (font, size, bold, colours, opacity, box) |
| Settings > Voice | engine, voice, speed, quality (Natural only) |
| Settings > Pronunciation | dictionary, project or all projects |
| Settings > AI models | provider, model, online keys and model, send photos |
| Settings > Setup | install voices, check Ollama, install moving photo clips |
| Project settings (project list) | route marker, animate photos, follow timing cues, fade into the stop's clip |
| Timeline Inspector | clip trim, volume, fades, subtitle text and style, title card style |

For the settings that Python understands but no screen offers, see [`BACKEND_GAPS.md`](./BACKEND_GAPS.md).

---

## 12. Recipes: how to change things

### 12.1 Add a field to a stop (Waypoint)

A stop's data travels through **four** places. Miss one and the field silently resets when the project is reopened.

1. `src/types/index.ts`: add the field to `Waypoint`.
2. `src/services/fileSystem.ts`, `saveProjectData`: write it into `processedWaypoints`.
3. `src/hooks/useWorkspace.tsx`, `loadProject`: read it in the loader map (**it does not keep unknown fields**).
4. If paths are involved, make them absolute in `loadProjectData` (`fileSystem.ts`).
5. If Python needs it, read it where waypoints are read and mention it in `JobConfigManager` path keys if it holds file paths.

Add a test next to the helper you touch (see `utils/waypointImages.ts`, `utils/photoCredits.ts` for examples).

### 12.2 Add a project setting

1. Add the key to `ProjectSettings` and a default in `defaultProjectSettings` (`config/constants.ts`).
2. Add a control in the right tab of `AppSettings.tsx` using `updateProject(patch)` (it marks the project dirty), or in `ProjectSettingsModal.tsx`
   (which must write the file *and* patch the database).
3. In Python read it with a fallback to `tuning`: `settings.get("my_key", tuning.MY_KEY)`.
4. App-wide choices (like the AI provider) are different: add the key to `AI_SETTING_KEYS` in `useWorkspace.tsx` or use `db.appSettings`.

### 12.3 Add or change UI text

```bash
npm run extract      # collects strings into src/locales/{en,ja}/messages.po
# fill in the Japanese msgstr entries in src/locales/ja/messages.po
npm run compile      # builds the .ts files the app loads
```

Changing the wording of an English message drops its Japanese translation (the key is the English text). Carry the translation over when you rename.
Prefer plain-English message ids. A few old ids are kebab-case keys whose English text is wrong; check the `en` catalog when you restyle one.

### 12.4 Add a Python mode

1. Write the handler in `services/cli/` (or reuse one). Return a dict: `{"success": True, ...}`; raise or return `{"success": False, "error": ...}` on failure.
2. Register the mode in `main.py` (the dispatcher) or, for voice-style utility modes, in `services/cli/voice_commands.py` (`VOICE_ACTIONS` and `_HANDLERS`).
3. Print **one JSON object as the last stdout line**; send progress to stderr (use `tracker`).
4. Call it from the frontend through `callSidecar("my_mode", {...})` in `services/sidecar.ts` clients. Remember: one call at a time.
5. Add a pytest in `src-tauri/src-python/tests/`.

### 12.5 Add a Rust command

1. Write `#[tauri::command] fn ...` (in `lib.rs` or a module).
2. Add it to `tauri::generate_handler![...]` in `lib.rs`.
3. If it needs a new permission (files, http), add it in `src-tauri/capabilities/default.json`.
4. Call it with `invoke("name", {...})`. Restart `tauri dev` (Rust changes are not hot-reloaded).

### 12.6 Add a voice engine

Copy the pattern of Kokoro: a server script (no Navivi imports) that runs in its own venv, a client class extending `_VenvEngineClient` in `ttsengine.py`
(own port, pid file, `.ready` marker), a `<engine>_setup.py` with an idempotent `install_<engine>()`, an action in `voice_commands.py`, a row in `ComponentsChecklist.tsx`,
a tab entry in `VoiceSettings.tsx`, the engine in the voice fingerprint, a cost model in `render_estimate.py`, and a credit in `config/credits.ts`.

### 12.7 Add a map style

Add an entry to the map styles in `config/constants.ts` (with `maxZoom` if the source stops early, as GSI does at 17). The Layers panel lists it automatically.

### 12.8 Add a context menu

Build the items (`MenuEntry[]`) and call `openContextMenu(event, items)` from `components/ui/menuItems.ts`. For map menus add to `features/map/hooks/useStopMenus.ts`.

### 12.9 Add a unit test

Frontend: put `name.test.ts(x)` next to the code. Tests run in plain Node; start a component or hook test with `// @vitest-environment jsdom`.
Python: `tests/test_*.py`; `conftest.py` resets the singletons. Use fakes for anything that needs a network, a GPU or a 26 GB download (see `test_comfyui_setup.py`).

### 12.10 Add a credit for a downloaded model

Add it to `src/config/credits.ts`. It shows in Settings > Setup and Settings > About. Check the license on the model's page first.

---

## 13. Fixing things: symptoms, causes, cures

First, find the log. For a render: the **System log** in the status bar, with the Details view. For Python: `services/logger/app.log`.
For Rust: the terminal where `tauri dev` runs. For the webview: right-click is disabled, but `F12` works in dev.

| Symptom | Likely cause | What to do |
|---|---|---|
| "Process was cancelled" or "was interrupted" | A second Python call started and killed the first (only one runs at a time) | Find the two callers. Make one wait, or use `callSidecarShared` for read-only calls that screens repeat |
| A setup dialog says "setup required" | An installed app has no pipeline Python yet (`SETUP_REQUIRED`) | Let the first-run setup finish (needs internet), or Settings > Setup |
| Map is blank or says no internet | Mapbox token missing, wrong, or restricted to another site | Settings > API keys, token must start with `pk.` |
| A leg cannot be routed | No OpenRouteService key, mode wrong, or a stop is far from any road | Add the key, change the mode, move the stop, or draw the leg |
| Everything changed but the **Python change is not visible** | An old process is still running, or `python` on PATH is a different install | Cancel the render, run again. Check `where python` |
| **Rust change is not visible** | `tauri dev` does not rebuild automatically for you | Stop and restart it |
| `npm run tauri dev` says port 1420 is in use | Another Vite or app instance | Close it (`strictPort` is on). In PowerShell: `Get-NetTCPConnection -LocalPort 1420` |
| Vite serves an empty module after you rewrote a file with a shell redirect | Windows file watcher | `touch` the file, or save it from an editor |
| A new stop field **disappears after reopening** | Not added to both the saver and the loader | Recipe 12.1 |
| A setting you changed in `job_config.json` is ignored | The database copy wins on open | Change it in the app, or also patch the database |
| Voice sounds wrong or a place name is misread | Engine mispronounces | Pronunciation dictionary, then **Redo voice** (dictionary changes do not remake existing audio) |
| First voice preview is very slow | The engine's server loads the model | Normal. Kokoro ~20 s, Irodori longer on CPU |
| Voice setup fails: "needs uv" | `uv.exe` not found | In dev: install uv. Installed app: it ships in `tools\uv.exe` |
| Voice server will not start or a render hangs at narration | A stale server holds the port or pid file | Kill `python` processes from the engine folders, delete the `.server.pid` in that engine folder, retry |
| Voices fail with a DLL error on a fresh PC | Missing Microsoft Visual C++ runtime (PyTorch needs `msvcp140.dll`) | Install `https://aka.ms/vs/17/release/vc_redist.x64.exe`. The setup program tries to do this |
| Photo clips just pan, never move | ComfyUI not installed, no NVIDIA GPU, or its server failed | Settings > Setup > Moving attraction videos. See `bin/ComfyUI/comfyui_server.log` |
| ComfyUI "rejected the workflow" | A model file name does not match `tuning.COMFYUI_*` | The file must have the exact name from `tuning.py` |
| `ffmpeg` not found | Not on PATH and not in `bin\FFmpeg` / `tools\ffmpeg` | `runtime_paths.ffmpeg_exe()` order: installer tools, `bin/FFmpeg`, PATH |
| Ollama: 403 or "model not found" | Origin blocked, or model not downloaded | Navivi sends an empty `Origin` (needs the plugin's `unsafe-headers` feature). Download the model in Settings > AI models |
| Online AI says no key | Key not in the credential store | Settings > AI models, press Test. Keys are per PC, never in project files |
| OpenRouter sign-in keeps waiting | Browser did not return to the loopback address | Press Cancel and retry, or paste a key |
| HEIC photo will not import | `pillow-heif` missing | `pip install pillow-heif` (it is in requirements.txt) |
| Photos found online return 403 | No `User-Agent` | Commons rejects requests without one; `placePhotos.ts` sets it. Keep it |
| Frontend tests fail only in CI | Node version, or a Windows-only test | CI uses Node 24; Python and Rust jobs run on Windows |
| `pytest` cannot import a package | You are using the repository `.venv`, which has no packages | Use the system `python` that has `requirements*.txt` installed |
| `npm run extract` complains about Node | Lingui CLI needs Node 24 | Update Node |
| Installed app starts but crashes before a window | WebView2 missing (Windows 10) | Install the Evergreen runtime. Our setup shows a message with the link |
| SmartScreen warns about the installer | It is not code-signed yet | "More info" > "Run anyway" |
| A project folder looks messy | An older version made it | Open it once; `tidy_project_folder` migrates it |
| Database errors or a project is missing from the list | Corrupt or missing `navivi.db` | Close the app, back up and delete `%APPDATA%\navivi\navivi.db`; reopen projects from their folders |

### Habits that prevent most bugs

- Do not write regex "patch scripts" to edit files: they corrupted encodings before. Edit files directly.
- Keep files UTF-8 without a BOM. Source contains Japanese text and em dashes.
- When you touch the pipeline's stages, run `python -m pytest tests/test_pipeline_stages.py`.
- A deleted line does not need a test to prove it is gone. Spend tests on behaviour that can break.

---

## 14. Tests and CI

| Suite | Command | Where | Notes |
|---|---|---|---|
| Frontend types | `npm run typecheck` | | `tsc --noEmit` |
| Frontend unit tests | `npm test` (`npm run test:watch` while editing) | `src/**/*.test.ts(x)` | Vitest + Testing Library + jsdom for components. About 280 tests |
| Python | `cd src-tauri/src-python && python -m pytest -q` | `tests/` | about 80 files, 770 test functions, a few minutes. Several run the real `ffmpeg` |
| Rust | `cargo test --manifest-path src-tauri/Cargo.toml` | in-file `#[cfg(test)]` | the process-kill test is Windows-only |
| End to end | `e2e/*.spec.ts` (Playwright) | | mocks `window.__TAURI_INTERNALS__`; needs a running dev server and an ad-hoc config (there is no `playwright.config`) |

CI (`.github/workflows/ci.yml`) runs on every push to `main` and every pull request:

1. **Frontend** (Ubuntu, Node 24): `npm ci`, typecheck, tests.
2. **Python pipeline** (Windows, Python 3.12): `requirements-test.txt`, the full pytest suite. FFmpeg comes from the runner.
3. **Rust shell** (Windows): `cargo test`.

A pull request should be green on all three before merging.

---

## 15. Build the installer

There are **two installers**. Use the first; the second is kept as a fallback.

| | Navivi setup program (current) | NSIS installer (old) |
|---|---|---|
| Command | `npm run build:setup` | `npm run build:installer` |
| Output | `setup/dist/Navivi-Setup-<version>.exe` (about 140 MB) | `src-tauri/target/release/bundle/nsis/` (about 114 MB) |
| Look | our own window (Rust + WebView2), Japanese or English by Windows language | standard NSIS pages with our pictures |
| Source | `setup/` | `src-tauri/installer/installer.nsi`, `tauri.installer.conf.json` |

### 15.1 What goes inside

- `navivi.exe`: the app, built with `tauri build --no-bundle`.
- `src-python/`: the pipeline code and assets, plus `requirements-runtime.txt`. **No** tests, data, `bin/`, `.env` or `.venv`.
- `tools/`: `ffmpeg.exe` and `ffprobe.exe` (gyan.dev essentials, has `libass` and `xfade`), `gpsbabel` (CLI only), and `uv.exe`.
- The bundled stock voices (`scripts/stock-voices.json`; only those with `verified: true`, with a `CREDITS.txt`).

**Not inside, on purpose:** Python (made on first run with `uv venv --python 3.12`, so the installer stays small), the voice engines, ComfyUI, Ollama, and your API keys.

### 15.2 Step by step

1. **Prerequisites** (section 2), plus `tar.exe` (built into Windows 10/11) and internet (the staging script downloads ffmpeg and uv the first time; downloads are cached in `scripts/.cache`).
2. **Get clean.** `git status` should show nothing you do not want shipped. Make sure `src-tauri/src-python/.env` is not meant to ship (it never is).
3. **Set the version.** Change it in all four places so they agree:
   - `package.json` → `"version"`
   - `src-tauri/tauri.conf.json` → `"version"` (the installer file name comes from this one)
   - `src-tauri/Cargo.toml` → `version`
   - `setup/Cargo.toml` → `version`
4. **Update credits** if you added bundled voices: `scripts/stock-voices.json` (set `verified: true` only after checking the license allows redistributing the audio).
5. **Run the checks:** `npm run typecheck && npm test`, and `python -m pytest -q` in `src-tauri/src-python`.
6. **Build:**

   ```bash
   npm run build:setup
   # to repackage without rebuilding the app (faster, when only src-python or the setup UI changed):
   npm run build:setup -- --skip-app
   ```

   The script does four things and prints them as `[1/4]` ... `[4/4]`:
   1. builds the app (`tauri build --no-bundle` → `src-tauri/target/release/navivi.exe`);
   2. stages code and tools (`scripts/stage-installer.mjs` → `src-tauri/installer-staging/`);
   3. zips `navivi.exe + src-python + tools + .navivi-install.json` into `setup/payload.zip` with Windows' own `tar.exe`;
   4. builds the setup program (`setup/`) and appends `[zip][footer "NAVIVIPL" + zip length]` to it → `setup/dist/Navivi-Setup-<version>.exe`.
7. **Test it without touching your own install** (next section).
8. **Hand it out.** Remember it is not code-signed: Windows SmartScreen will warn ("More info" > "Run anyway").

### 15.3 Test the installer safely

`setup/dist/`, `setup/stage/` and `setup/payload.zip` are git-ignored (GitHub rejects files over 100 MB).

```bash
# silent install into a throwaway folder, no shortcuts, do not start the app
Navivi-Setup-1.0.0.exe --silent --dir C:\Temp\navivi-test --no-launch --no-shortcuts --log C:\Temp\install.log

# silent uninstall (also removes downloaded tools and voices)
C:\Temp\navivi-test\uninstall.exe --uninstall --silent --remove-data
```

Flags: `--silent`, `--dir X`, `--no-launch`, `--no-shortcuts`, `--log file`; the uninstaller adds `--uninstall`, `--remove-data`.
A folder that already holds other files gets a `Navivi` sub-folder, so nothing is mixed up.

Drive the **installed** app without stealing your mouse: start it with
`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333` and connect Playwright with `connectOverCDP`.
**Windows Sandbox** (a clean throwaway Windows) is the best test for "does it work on a PC that has nothing installed": it exercises the WebView2 and Visual C++ runtime
paths that your own PC hides.

> Careful: both installers write the same "Apps & features" entry (`HKCU\...\Uninstall\Navivi`). Do not run a test uninstall on a PC that has a *different* real install.

### 15.4 What the user sees on first run

1. Setup program: choose a folder (default `%LOCALAPPDATA%\Programs\Navivi`), shortcuts, install. Last step: if the Microsoft Visual C++ runtime is missing it downloads and installs it (Windows asks for permission; failure only adds a note).
2. First launch: a dialog creates the pipeline's Python (`uv venv --python 3.12`, `uv pip install -r requirements-runtime.txt`, `playwright install chromium`). About 800 MB, internet needed.
3. A checklist offers the optional parts (voices, local AI, moving photo clips). It is also under Settings > Setup.

### 15.5 Changing how the installer looks

- NSIS pictures: `npm run art:installer` redraws `src-tauri/installer/sidebar.bmp` and `header.bmp` from the logo.
- Our setup window: `setup/ui/index.html` (one file: CSS, JavaScript and the Japanese/English strings). Logic in `setup/src/` (`install.rs` steps, `payload.rs` zip reader, `system.rs` shortcuts and registry, `main.rs` window).
- The setup program links the C runtime statically (`setup/.cargo/config.toml`) so it starts on a clean PC.

### 15.6 If the build fails

| Message | Cause | Cure |
|---|---|---|
| `link.exe not found` | no C++ build tools | install Visual Studio Build Tools with the C++ workload and a Windows SDK |
| `tar` errors about `./` or zip | a GNU `tar` from Git Bash is first on PATH | the script already calls `C:\Windows\System32\tar.exe`; do not change that |
| download fails in staging | no internet or a blocked URL | rerun; files already downloaded are cached in `scripts/.cache` |
| installer is huge | `bin/` or `.venv` got staged | check `scripts/stage-installer.mjs` excludes; never ship `bin/` |
| payload not found at runtime | footer missing | rebuild with `npm run build:setup` (do not run `cargo build` alone: it makes a setup with no payload) |

---

## 16. Release checklist

Copy this into the pull request or a ticket.

- [ ] All three CI jobs are green on `main`.
- [ ] Version bumped in `package.json`, `tauri.conf.json`, `Cargo.toml`, `setup/Cargo.toml`.
- [ ] `npm run extract`, Japanese filled in, `npm run compile`; no untranslated strings.
- [ ] `docs/FEATURES.md` and the user manual updated for new features (manual pictures come from the browser harness).
- [ ] `npm run build:setup`.
- [ ] Silent install into a temp folder works; the app starts; first-run setup finishes.
- [ ] A short test project: add three stops, generate with Fast render, export.
- [ ] A Windows Sandbox run (clean PC) if the setup program or runtime handling changed.
- [ ] Uninstall removes the app and shortcuts but not the user's projects.
- [ ] Credits in Settings > About are right for every bundled model and voice.
- [ ] Tag the commit (`git tag v1.0.0`) and keep the installer file with the tag.

---

## 17. Working with git

- Remote `origin` is `github.com/mzxrq/navivi`; `main` is the default branch. Work happens on `feature/*`, `frontend/*`, `chore/*` branches and lands through pull requests.
- **Direction matters.** A pull request merges the *head* branch **into** the *base* branch. For "put my work on main" the base is `main` and the head is your branch.
  The GitHub button "Update branch" does the opposite (it merges the base into your branch). That is harmless but adds a merge commit.
- Commit subjects start with `feat:`, `fix:`, `chore:` or `docs:`. One logical change per commit.
- No `Co-Authored-By` or "Generated with" lines in commits or pull request descriptions.
- The pull request template is `docs/pull_request_template.md` (what, why, how to check, checks, not tested, notes). GitHub fills it in when the template is on the base branch.
- Do not commit: `.env`, anything under `src-tauri/src-python/bin/`, `data/`, installers, `node_modules`.

---

## 18. Not done yet

Known and accepted gaps. The full audit of Python features without a screen is in [`BACKEND_GAPS.md`](./BACKEND_GAPS.md).

- Code signing for the installer (SmartScreen warning) and auto-update.
- A smaller FFmpeg (two 100 MB executables).
- An Ollama installer (we only link to its download page).
- The Visual C++ runtime check in the setup program and the ComfyUI installer have only been unit-tested, not run on a clean PC / a GPU PC.
- The assistant, the photo finder and the per-project chat have never been tried by a human in the real app.
- Splitting a clip, per-clip transitions other than the fade, and resolution settings in the timeline editor.
- `e2e/` has no config file and is not part of CI.

---

## 19. Glossary

| Word | Meaning |
|---|---|
| Stop / waypoint | a place in the route with its own scripts and photos |
| Stop-by | a place the route passes through; it shapes the route but has no photo clip |
| Leg | the line between two stops, with its own travel mode |
| Via point | an extra point that bends a leg's route |
| Arriving script | narration while travelling to a stop |
| Attraction script | narration at the stop, over its photos |
| Asset | any generated file: voice, subtitles, route clip, photo clip, card |
| Clip | one piece of the final video |
| Sidecar | the Python process the Rust shell starts |
| Blueprint | historical name for a sidecar call (`run_python_blueprint`) |
| Residential | the per-leg route video (as opposed to the overview) |
| Overview | the opening map shot of the whole route |
| `.nvv` | a project packed into one zip file for sharing |
| Harness | the browser page that mounts the real app with a fake Tauri, used for screenshots |
| Lingui | the translation library (`t` and `<Trans>` macros, `.po` catalogs) |
| uv | a fast Python package and environment tool, used to build engine and runtime environments |
| ComfyUI | a local image/video generation server used for moving photo clips |
| GSI | Japan's Geospatial Information Authority; its map data fills walking-route gaps |
