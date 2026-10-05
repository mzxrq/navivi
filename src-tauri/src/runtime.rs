//! Where the media pipeline's Python and tools are.
//!
//! From the repo (`tauri dev`) the working directory is `src-tauri`, `python` is whatever is on PATH and the tools sit in
//! `src-python/bin`. In the installed app the code and the small tools ship in the install folder (read-only) and the
//! heavy parts are made on first run in the user's local app data:
//!
//! ```text
//! <install>/src-python/        the pipeline code            (resource)
//! <install>/tools/             ffmpeg/, gpsbabel/, uv.exe   (resource)
//! <local data>/runtime/venv    the pipeline's Python        (made by `runtime_install`)
//! <local data>/bin             voice engines, ComfyUI, Ollama, recorded voices
//! ```

use serde::Serialize;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::OnceLock;
use tauri::{AppHandle, Emitter};

const VENV_PYTHON_VERSION: &str = "3.12";

#[derive(Debug, Clone, PartialEq)]
pub struct Runtime {
    /// Running from an installed app (as opposed to the repo).
    pub installed: bool,
    pub python: PathBuf,
    pub script: PathBuf,
    pub cwd: Option<PathBuf>,
    pub bin_dir: Option<PathBuf>,
    pub tools_dir: Option<PathBuf>,
    pub venv_dir: Option<PathBuf>,
    pub requirements: Option<PathBuf>,
}

/// What the shell can see of the machine; separate from `resolve` so the decision can be tested.
pub struct Layout {
    pub dev_script_exists: bool, // see running_from_repo
    pub resource_dir: Option<PathBuf>,
    pub local_data_dir: Option<PathBuf>,
}

pub fn venv_python_in(venv: &Path) -> PathBuf {
    if cfg!(windows) {
        venv.join("Scripts").join("python.exe")
    } else {
        venv.join("bin").join("python")
    }
}

/// Windows hands out `\\?\C:\...` for some folders; Python and uv are happier without the prefix.
pub fn clean_path(p: PathBuf) -> PathBuf {
    match p.to_str().and_then(|s| s.strip_prefix(r"\\?\")) {
        Some(rest) => PathBuf::from(rest),
        None => p,
    }
}

pub fn resolve(layout: &Layout) -> Runtime {
    if layout.dev_script_exists {
        return Runtime {
            installed: false,
            python: PathBuf::from("python"),
            script: PathBuf::from("src-python/main.py"),
            cwd: None,
            bin_dir: None,
            tools_dir: None,
            venv_dir: None,
            requirements: None,
        };
    }
    let resources = layout.resource_dir.clone().unwrap_or_default();
    let data = layout.local_data_dir.clone().unwrap_or_default();
    let venv = data.join("runtime").join("venv");
    Runtime {
        installed: true,
        python: venv_python_in(&venv),
        script: resources.join("src-python").join("main.py"),
        cwd: Some(data.clone()),
        bin_dir: Some(data.join("bin")),
        tools_dir: Some(resources.join("tools")),
        venv_dir: Some(venv),
        requirements: Some(resources.join("src-python").join("requirements-runtime.txt")),
    }
}

/// Whether this is a development run from the repo. Only a debug build can be: an installed app's working directory is its
/// install folder, which also holds `src-python/main.py`, so the file alone proves nothing.
pub fn running_from_repo() -> bool {
    cfg!(debug_assertions) && Path::new("src-python/main.py").exists()
}

static RUNTIME: OnceLock<Runtime> = OnceLock::new();

pub fn init(layout: Layout) {
    let _ = RUNTIME.set(resolve(&layout));
}

/// The runtime for this process; the repo layout if `init` was never called (tests, tools).
pub fn get() -> &'static Runtime {
    RUNTIME.get_or_init(|| {
        resolve(&Layout {
            dev_script_exists: running_from_repo(),
            resource_dir: None,
            local_data_dir: None,
        })
    })
}

/// No console window for a child of the GUI app (a release build would otherwise flash one per call).
pub fn hide_window(cmd: &mut Command) -> &mut Command {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    cmd
}

impl Runtime {
    pub fn python_ready(&self) -> bool {
        !self.installed || self.python.exists()
    }

    /// `python main.py` ready to take its arguments, with the folders the pipeline asks for (see runtime_paths.py).
    pub fn command(&self) -> Command {
        let mut cmd = Command::new(&self.python);
        cmd.env("PYTHONIOENCODING", "utf-8").arg(&self.script);
        if let Some(cwd) = &self.cwd {
            let _ = std::fs::create_dir_all(cwd);
            cmd.current_dir(cwd);
        }
        if let Some(bin) = &self.bin_dir {
            let _ = std::fs::create_dir_all(bin);
            cmd.env("NAVIVI_BIN_DIR", bin);
        }
        if let Some(tools) = &self.tools_dir {
            cmd.env("NAVIVI_TOOLS_DIR", tools);
            let uv = tools.join(if cfg!(windows) { "uv.exe" } else { "uv" });
            if uv.exists() {
                cmd.env("NAVIVI_UV", uv);
            }
        }
        hide_window(&mut cmd);
        cmd
    }

    /// The uv that makes Python environments: shipped in the installer, or one on PATH.
    pub fn uv(&self) -> PathBuf {
        let name = if cfg!(windows) { "uv.exe" } else { "uv" };
        match &self.tools_dir {
            Some(tools) if tools.join(name).exists() => tools.join(name),
            _ => PathBuf::from("uv"),
        }
    }

    /// GPSBabel: shipped, then the repo's bin folder, then PATH.
    pub fn gpsbabel(&self) -> PathBuf {
        let name = if cfg!(windows) { "gpsbabel.exe" } else { "gpsbabel" };
        let mut candidates = Vec::new();
        if let Some(tools) = &self.tools_dir {
            candidates.push(tools.join("gpsbabel").join(name));
        }
        candidates.push(self.bin_dir.clone().unwrap_or_else(|| PathBuf::from("src-python/bin")).join("GPSBabel").join(name));
        candidates.into_iter().find(|p| p.exists()).unwrap_or_else(|| PathBuf::from("gpsbabel"))
    }

    /// Where an Ollama build we downloaded would be.
    pub fn bundled_ollama(&self) -> PathBuf {
        let bin = self.bin_dir.clone().unwrap_or_else(|| PathBuf::from("src-python/bin"));
        bin.join("ollama-windows-amd64").join("ollama.exe")
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeStatus {
    /// An installed app (not `tauri dev`): the setup screen applies.
    pub installed: bool,
    pub python_ready: bool,
    pub uv_found: bool,
    pub venv_dir: Option<String>,
}

#[tauri::command]
pub fn runtime_status() -> RuntimeStatus {
    let rt = get();
    let uv = rt.uv();
    RuntimeStatus {
        installed: rt.installed,
        python_ready: rt.python_ready(),
        uv_found: uv.exists() || Command::new(&uv).arg("--version").output().is_ok(),
        venv_dir: rt.venv_dir.as_ref().map(|p| p.display().to_string()),
    }
}

/// The two commands that make the pipeline's Python: a venv from uv's own Python, then the requirements. Pure so it can be tested.
pub fn install_steps(rt: &Runtime) -> Result<Vec<(String, Vec<String>)>, String> {
    let venv = rt.venv_dir.as_ref().ok_or("This is a development build; the Python on PATH is used.")?;
    let requirements = rt.requirements.as_ref().ok_or("No requirements file is known.")?;
    let python = rt.python.display().to_string();
    Ok(vec![
        (
            "Creating the Python environment".into(),
            vec!["venv".into(), "--python".into(), VENV_PYTHON_VERSION.into(), venv.display().to_string()],
        ),
        (
            "Installing the media tools".into(),
            vec![
                "pip".into(),
                "install".into(),
                "--python".into(),
                python,
                "-r".into(),
                requirements.display().to_string(),
            ],
        ),
    ])
}

static INSTALLING: AtomicBool = AtomicBool::new(false);

#[derive(Serialize, Clone)]
struct SetupStep {
    index: usize,
    total: usize,
    title: String,
}

/// Runs a child to the end, sending each line it prints to the setup screen as `setup-log`.
fn run_logged(app: &AppHandle, mut cmd: Command, title: &str) -> Result<(), String> {
    // Plain text for the log panel: no color codes, no animated progress bars.
    cmd.env("NO_COLOR", "1").env("UV_NO_PROGRESS", "1").stdout(Stdio::piped()).stderr(Stdio::piped());
    hide_window(&mut cmd);
    let mut child = cmd.spawn().map_err(|e| format!("{title}: {e}"))?;
    let stderr = child.stderr.take().ok_or("no stderr")?;
    let stdout = child.stdout.take().ok_or("no stdout")?;
    let for_stderr = app.clone();
    let reader = std::thread::spawn(move || {
        for line in BufReader::new(stderr).lines().map_while(Result::ok) {
            let _ = for_stderr.emit("setup-log", line);
        }
    });
    for line in BufReader::new(stdout).lines().map_while(Result::ok) {
        let _ = app.emit("setup-log", line);
    }
    let _ = reader.join();
    let status = child.wait().map_err(|e| format!("{title}: {e}"))?;
    if status.success() {
        Ok(())
    } else {
        Err(format!("{title} failed (exit code {}). See the log above.", status.code().unwrap_or(-1)))
    }
}

fn install_blocking(app: &AppHandle) -> Result<(), String> {
    let rt = get();
    let steps = install_steps(rt)?;
    let total = steps.len() + 1;
    let uv = rt.uv();

    for (i, (title, args)) in steps.iter().enumerate() {
        let _ = app.emit("setup-step", SetupStep { index: i + 1, total, title: title.clone() });
        if args[0] == "venv" && rt.python.exists() {
            continue; // already made; the next step repairs whatever is missing
        }
        let mut cmd = Command::new(&uv);
        cmd.args(args);
        run_logged(app, cmd, title)?;
    }

    let title = "Downloading the browser used to draw the route";
    let _ = app.emit("setup-step", SetupStep { index: total, total, title: title.into() });
    let mut cmd = Command::new(&rt.python);
    cmd.args(["-m", "playwright", "install", "chromium"]);
    run_logged(app, cmd, title)
}

/// Makes the pipeline's Python (from uv's own Python 3.12) and installs what the media tools need, with progress events
/// `setup-step` / `setup-log`. Safe to run again to repair a half-finished setup.
#[tauri::command]
pub async fn runtime_install(app: AppHandle) -> Result<(), String> {
    if INSTALLING.swap(true, Ordering::SeqCst) {
        return Err("Setup is already running.".into());
    }
    let worker = app.clone();
    let result = tauri::async_runtime::spawn_blocking(move || install_blocking(&worker))
        .await
        .map_err(|e| e.to_string())
        .and_then(|r| r);
    INSTALLING.store(false, Ordering::SeqCst);
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    fn installed_layout() -> Layout {
        Layout {
            dev_script_exists: false,
            resource_dir: Some(PathBuf::from("C:/Apps/Navivi")),
            local_data_dir: Some(PathBuf::from("C:/Users/u/AppData/Local/navivi")),
        }
    }

    #[test]
    fn the_repo_layout_uses_the_python_on_path_and_the_relative_script() {
        let rt = resolve(&Layout { dev_script_exists: true, resource_dir: None, local_data_dir: None });
        assert!(!rt.installed);
        assert_eq!(rt.python, PathBuf::from("python"));
        assert_eq!(rt.script, PathBuf::from("src-python/main.py"));
        assert!(rt.cwd.is_none() && rt.bin_dir.is_none() && rt.tools_dir.is_none());
        assert!(rt.python_ready());
    }

    #[test]
    fn an_installed_app_keeps_code_in_resources_and_everything_writable_in_local_data() {
        let rt = resolve(&installed_layout());
        assert!(rt.installed);
        assert_eq!(rt.script, PathBuf::from("C:/Apps/Navivi/src-python/main.py"));
        assert_eq!(rt.tools_dir, Some(PathBuf::from("C:/Apps/Navivi/tools")));
        assert_eq!(rt.bin_dir, Some(PathBuf::from("C:/Users/u/AppData/Local/navivi/bin")));
        assert_eq!(rt.cwd, Some(PathBuf::from("C:/Users/u/AppData/Local/navivi")));
        assert_eq!(rt.python, venv_python_in(&PathBuf::from("C:/Users/u/AppData/Local/navivi/runtime/venv")));
        assert!(!rt.python_ready(), "no venv exists yet");
    }

    #[test]
    fn the_extended_length_prefix_is_removed() {
        assert_eq!(clean_path(PathBuf::from(r"\\?\C:\Apps\Navivi")), PathBuf::from(r"C:\Apps\Navivi"));
        assert_eq!(clean_path(PathBuf::from("C:/Apps")), PathBuf::from("C:/Apps"));
    }

    #[test]
    fn setup_makes_a_venv_then_installs_the_requirements_into_it() {
        let rt = resolve(&installed_layout());
        let steps = install_steps(&rt).unwrap();
        assert_eq!(steps.len(), 2);
        assert_eq!(steps[0].1[0], "venv");
        assert!(steps[0].1.contains(&"3.12".to_string()));
        assert!(steps[0].1.last().unwrap().ends_with("venv"));
        assert_eq!(steps[1].1[..3], ["pip", "install", "--python"]);
        assert!(steps[1].1.last().unwrap().ends_with("requirements-runtime.txt"));
    }

    #[test]
    fn a_development_build_has_nothing_to_set_up() {
        let rt = resolve(&Layout { dev_script_exists: true, resource_dir: None, local_data_dir: None });
        assert!(install_steps(&rt).is_err());
    }

    #[test]
    fn the_command_carries_the_folders_the_pipeline_looks_up() {
        let dir = std::env::temp_dir().join("navivi-runtime-test");
        let rt = Runtime {
            installed: true,
            python: PathBuf::from("python"),
            script: PathBuf::from("main.py"),
            cwd: Some(dir.clone()),
            bin_dir: Some(dir.join("bin")),
            tools_dir: Some(dir.join("tools")),
            venv_dir: None,
            requirements: None,
        };
        let cmd = rt.command();
        let envs: std::collections::HashMap<_, _> = cmd.get_envs().map(|(k, v)| (k.to_string_lossy().into_owned(), v.map(|v| v.to_string_lossy().into_owned()))).collect();
        assert_eq!(envs["PYTHONIOENCODING"].as_deref(), Some("utf-8"));
        assert_eq!(envs["NAVIVI_BIN_DIR"].as_deref(), Some(dir.join("bin").to_str().unwrap()));
        assert_eq!(envs["NAVIVI_TOOLS_DIR"].as_deref(), Some(dir.join("tools").to_str().unwrap()));
        assert_eq!(cmd.get_current_dir(), Some(dir.as_path()));
        let _ = std::fs::remove_dir_all(&dir);
    }
}
