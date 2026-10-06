[<img width="300" alt="Navivi logo" src="public/navivi.svg">](#)

[![CI](https://github.com/mzxrq/navivi/actions/workflows/ci.yml/badge.svg)](https://github.com/mzxrq/navivi/actions/workflows/ci.yml)

**Navivi** is a desktop app that turns a route into a narrated, cinematic travel video. Plot stops on a map or import a GPS track, write (or generate) a short script for each place, and Navivi renders the animated route, voices the narration, adds your photos and videos, and stitches everything into one video you can finish in a built-in editor.

It runs locally: the interface is React inside Tauri, and a Python sidecar does the heavy work (map rendering, text-to-speech, video encoding). Nothing has to be uploaded to a cloud service.

## What you can do

- **Plan a route on a 3D map.** Drive, walk, ferry, draw a path by hand, or fly in a straight curve between stops. Every leg can have its own line colour.
- **Import what you already have.** GPX, FIT, TCX and KML tracks (stops are placed along the real recorded track), or drop photos with location data onto the map (iPhone HEIC photos are converted to JPEG on the way in, GPS tags kept).
- **Write narration your way.** Per-stop scripts, optionally drafted by a local Ollama model that sticks to the facts it is given, with a pronunciation dictionary (per project and shared by all projects) for names the voice gets wrong.
- **Choose a voice.** Pick a narration voice, clone a new one from a short recording, set the speed and preview it.
- **Use your own footage.** Add photos or your own videos to a stop. Photos can be animated; videos play in place, fitted to the narration, with their sound off unless you turn it on.
- **Finish in the timeline editor.** Reorder and trim clips, shift narration, add subtitles (from the narration, or from an SRT file, even one without timestamps), add background music, then export one video. An "Auto edit" button orders the clips and fills in fades and subtitles.
- **Share a project.** Export a lean `.nvv` file (a zip) that a friend can open on their own machine.

## How it fits together

| Layer          | Where                   | Role                                                                                                                                                                        |
| -------------- | ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Frontend       | `src/`                  | React 19, TypeScript, Vite, Tailwind v4. Map editor (Mapbox GL), timeline editor, render and settings UI. Translations: English and Japanese (Lingui).                      |
| Shell          | `src-tauri/src/`        | Thin Rust layer: starts the Python sidecar and streams its logs, project archive and tidy commands, the local database (SQLite) for projects, settings and version history. |
| Media pipeline | `src-tauri/src-python/` | GPS parsing, text-to-speech, subtitles, attraction clips, route rendering (pydeck + headless Chromium), timeline and export with FFmpeg.                                    |

Optional local services, started on demand: **Ollama** (scripts), **Irodori TTS** (voices) and **ComfyUI** with Wan 2.2 (animating photos; without it Navivi falls back to a simple pan and zoom).

## Getting started

You need Node.js 18+, Rust, Python 3.12+ and FFmpeg (on your PATH or in `src-tauri/src-python/bin`). Ollama and ComfyUI are optional.

```bash
# 1. Python dependencies for the sidecar
cd src-tauri/src-python
pip install -r requirements.txt
cd ../..

# 2. Frontend dependencies
npm install

# 3. API keys: copy the example and fill in VITE_MAPBOX_TOKEN and VITE_ORS_API_KEY
cp .env.example .env

# 4. Run the app (starts Vite and builds the Rust shell)
npm run tauri dev
```

More detail: [Getting started](./docs/GETTING_STARTED.md), [Features](./docs/FEATURES.md), and the [Developer guide](./docs/DEVELOPER_GUIDE.md) (every part, how to fix, run and build the installer). Backend features without a screen yet: [Backend gaps](./docs/BACKEND_GAPS.md).

## Checks

The same three checks run on every pull request (`.github/workflows/ci.yml`):

```bash
npm run typecheck && npm test                              # TypeScript, and the frontend unit tests (Vitest)
cd src-tauri/src-python && pip install -r requirements-test.txt && python -m pytest -q   # media pipeline
cargo test --manifest-path src-tauri/Cargo.toml            # Rust shell
```

## Where your projects live

Projects are folders under `Documents/Navivi/Workspaces/<project>/`:

```text
<project>/
  job_config.json    the project (route, scripts, settings), also what the Python pipeline reads
  timeline.json      your edit
  thumbnail.png
  raw_track.gpx
  assets/            image, audio, subtitles, video (route, attraction, user)
  .navivi/           generated bookkeeping (route cache, narration cues, gps data)
```

Map tiles are cached once for all projects in `Documents/Navivi/Cache/tiles`. To send a project to someone, use **Export for sharing**: the file leaves out caches and rebuildable clips (add them with one switch). Folders made by older versions are tidied automatically the first time they are opened.
