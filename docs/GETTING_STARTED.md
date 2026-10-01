# Getting Started with Navivi

## Prerequisites

To build and run Navivi locally, you will need the following installed on your system:

- [Node.js](https://nodejs.org/) (v18+)
- [Rust](https://www.rust-lang.org/tools/install)
- [Python 3.12+](https://www.python.org/)
- **FFmpeg** (on your system PATH, or placed in `src-tauri/src-python/bin/FFmpeg`)
- _(Optional)_ **Ollama** and **ComfyUI** running locally for AI script and video generation.

## Setup Instructions

**1. Install Python Dependencies**
The Python sidecar handles video rendering and AI synthesis. Navigate to the Python source directory and install the required packages:

```bash
cd src-tauri/src-python
pip install -r requirements.txt
```

**2. Install Frontend Dependencies**
Return to the project root and install the Node modules:

```bash
# Return to the root directory if you are in the python folder
cd ../../
npm install
```

**3. Configure Environment Variables**
Copy the example environment file and add your API keys (`VITE_MAPBOX_KEY` and `VITE_ORS_API_KEY`):

```bash
cp .env.example .env
```

**4. Run in Development Mode**
Start the application. This will automatically boot the Vite development server and compile the Rust backend:

```bash
npm run tauri dev
```

## Running the tests

```bash
cd src-tauri && cargo test
cd src-tauri/src-python && python -m pytest -q
npx tsc --noEmit
```

## Where projects are saved

Projects are folders in `Documents/Navivi/Workspaces`. Use **Export for sharing** (editor menu, or the project's menu in the Project Manager) to make one `.nvv` file to send to someone. See the [README](../README.md) for the folder layout.
