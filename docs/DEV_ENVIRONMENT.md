# Development environment: install and uninstall

How to set up Navivi for development on Windows, and how to remove it cleanly.
Everything project-specific lives inside the repository folder, except a few global tools and your own data.

Run all commands in PowerShell from the repository root (`C:\Users\ACER\Desktop\work\navivi`).

## Install

### 1. Global tools (outside the project)

```powershell
winget install OpenJS.NodeJS.LTS
winget install Python.Python.3.12
winget install Rustlang.Rustup
```

Requirements: Node.js 18+, Python 3.12+, Rust (via rustup). WebView2 ships with Windows 11.

FFmpeg does not need a global install. Place it in `src-tauri\src-python\bin\FFmpeg` (gitignored); the app checks there before PATH.

### 2. Python environment (inside the project)

The Rust shell runs whichever `python` is first on PATH, not the `.venv` by default. Activate this venv in the same terminal you use to start the app.

```powershell
python -m venv --clear .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r src-tauri\src-python\requirements-test.txt
python -m playwright install chromium
```

`requirements-test.txt` covers the media pipeline and its tests. Add `requirements.txt` only if you need the optional AI photo fallback: it pulls in PyTorch (several GB), so install torch first as described in that file.

### 3. Frontend and API keys

```powershell
npm install
copy .env.example .env
```

Edit `.env` and fill in `VITE_MAPBOX_TOKEN` and `VITE_ORS_API_KEY`.

### 4. Run the app

In the same terminal, with the venv still active:

```powershell
npm run tauri dev
```

### Optional

- **Ollama** (local AI scripts): install from ollama.com. Not managed by Navivi.
- **ComfyUI + Wan 2.2** (animated photos): installed from Settings > Setup. Falls back to a simple pan without it.

## Uninstall

### 1. Project files (inside the repository)

```powershell
Remove-Item -Recurse -Force .venv, node_modules, src-tauri\target, src-tauri\src-python\bin, src-tauri\src-python\.pytest_cache -ErrorAction SilentlyContinue
```

`src-tauri\src-python\bin` holds FFmpeg and any voice engines or ComfyUI installed from Settings, so it is usually the largest item.

### 2. Your projects and caches (outside the repository)

Back up `Documents\Navivi` first if you want to keep any projects. It is not part of the repo and the commands below delete it.

```powershell
Remove-Item -Recurse -Force "$env:USERPROFILE\Documents\Navivi"
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\ms-playwright"
Remove-Item -Recurse -Force "$env:USERPROFILE\.cache\huggingface"
```

- `Documents\Navivi`: projects, map-tile cache.
- `ms-playwright`: Chromium installed in step 2.
- `.cache\huggingface`: speech and OCR models, if downloaded.

### 3. Global tools (only if installed just for this project)

```powershell
winget uninstall Rustlang.Rustup
winget uninstall Python.Python.3.12
winget uninstall OpenJS.NodeJS.LTS
```

If `%USERPROFILE%\.rustup` or `%USERPROFILE%\.cargo` remain, run `rustup self uninstall` before removing Rustup.

Uninstall Ollama from its own uninstaller if you installed it.
