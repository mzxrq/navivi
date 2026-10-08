mod project_files;
mod runtime;
mod oauth;
mod secrets;
use std::net::TcpStream;
use std::process::{Child, Command, Stdio};
use std::io::{BufRead, BufReader};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::{thread};
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager, State};
use std::path::Path;
use std::fs;

mod db;

// Killing python.exe alone leaves what the pipeline started (ffmpeg, headless Chromium, the TTS and ComfyUI servers) running
// and holding the GPU and open files, so the whole process tree goes.
fn kill_tree(child: &mut Child) {
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        let _ = Command::new("taskkill")
            .args(["/PID", &child.id().to_string(), "/T", "/F"])
            .creation_flags(0x0800_0000) // CREATE_NO_WINDOW
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
    let _ = child.kill();
}

// Startup: a small "splash" window plays the logo while the (hidden) main window loads; app_ready swaps them.
struct StartedAt(std::time::Instant);
const SPLASH_MIN: Duration = Duration::from_millis(3600);
const SPLASH_GIVE_UP: Duration = Duration::from_secs(25);

fn reveal_main(app: &AppHandle) {
    if let Some(splash) = app.get_webview_window("splash") {
        if let Some(main) = app.get_webview_window("main") {
            let _ = main.show();
            let _ = main.set_focus();
        }
        let _ = splash.close();
    }
}

#[tauri::command]
async fn app_ready(app: AppHandle, started: State<'_, StartedAt>) -> Result<(), String> {
    let wait = SPLASH_MIN.saturating_sub(started.0.elapsed());
    if !wait.is_zero() {
        tauri::async_runtime::spawn_blocking(move || thread::sleep(wait)).await.map_err(|e| e.to_string())?;
    }
    reveal_main(&app);
    Ok(())
}

struct BlueprintState {
    process: Mutex<Option<Child>>,
    render_process: Mutex<Option<Child>>,
    render_cancelled: AtomicBool,
}

fn kill_tracked_children(state: &BlueprintState) {
    if let Ok(mut lock) = state.process.lock() {
        if let Some(mut child) = lock.take() {
            kill_tree(&mut child);
        }
    }
    if let Ok(mut lock) = state.render_process.lock() {
        if let Some(mut child) = lock.take() {
            kill_tree(&mut child);
        }
    }
}


/// `python main.py` for this build (the repo's, or the installed app's own), with the saved AI keys and the app-wide
/// Mapbox token (`NAVIVI_MAPBOX_TOKEN`) in its environment.
/// Fails with a `SETUP_REQUIRED` message the frontend turns into the setup screen when an installed app has no Python yet.
fn vc_runtime_guard() -> Result<(), String> {
    if runtime::vc_runtime_present() {
        Ok(())
    } else {
        Err("VC_RUNTIME_MISSING: the Microsoft Visual C++ runtime is not installed.".into())
    }
}

fn python_command(app: &AppHandle) -> Result<Command, String> {
    let rt = runtime::get();
    if !rt.python_ready() {
        return Err("SETUP_REQUIRED: the media tools are not installed yet.".into());
    }
    let mut cmd = rt.command();
    secrets::export_keys(&mut cmd);
    let token = app
        .try_state::<db::DbState>()
        .and_then(|state| state.0.lock().ok().and_then(|conn| db::app_settings::api_key(&conn, "mapbox")));
    if let Some(token) = token {
        cmd.env("NAVIVI_MAPBOX_TOKEN", token);
    }
    Ok(cmd)
}

#[tauri::command]
async fn run_python_blueprint(
    app: AppHandle,
    action: String,
    payload: String,
    state: State<'_, BlueprintState>
) -> Result<String, String> {

    // Spawn instead of output()
    let mut cmd = python_command(&app)?;
    cmd.arg(&action)
        .arg(&payload)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let mut child = cmd.spawn().map_err(|e| e.to_string())?;

    // Extract the pipes before moving the child to the state
    let mut stdout = child.stdout.take().ok_or("Failed to capture stdout")?;
    let stderr = child.stderr.take().ok_or("Failed to capture stderr")?;

    // 2. Lock the Mutex and store the child process safely
    let my_pid = child.id();
    {
        let mut lock = state.process.lock().unwrap();
        // If there's an existing process stuck, kill it before starting a new one
        if let Some(mut old_child) = lock.take() {
            kill_tree(&mut old_child);
            let _ = old_child.wait();
        }
        *lock = Some(child);
    }

    // 3. Read stderr on a separate thread to prevent OS pipe deadlocks
    // Each line is also sent to the window as `blueprint-log` so long installs can show progress; the full text is still kept for the error.
    let app_for_log = app.clone();
    let stderr_thread = thread::spawn(move || {
        let mut err_str = String::new();
        for line in std::io::BufReader::new(stderr).split(b'\n').map_while(Result::ok) {
            let line = String::from_utf8_lossy(&line).trim_end_matches('\r').to_string();
            let _ = app_for_log.emit("blueprint-log", line.clone());
            err_str.push_str(&line);
            err_str.push('\n');
        }
        err_str
    });

    // 4. Read stdout on the main task thread
    // This will naturally block here until the process finishes OR gets killed.
    let mut out_str = String::new();
    let _ = stdout.read_to_string(&mut out_str);

    let err_str = stderr_thread.join().unwrap_or_default();

    // 5. Streams are closed. Clean up and get the exit status.
    // Only this call's own process is reaped here: if a newer call (or a cancel) replaced it, the slot holds someone else's child.
    let mut lock = state.process.lock().unwrap();
    if lock.as_ref().map(|c| c.id()) == Some(my_pid) {
        if let Some(mut child) = lock.take() {
            match child.wait() {
                Ok(status) => {
                    if status.success() {
                        return Ok(out_str);
                    } else {
                        return Err(if err_str.is_empty() { "Process terminated".to_string() } else { err_str });
                    }
                }
                Err(e) => return Err(e.to_string()),
            }
        }
    }

    // The slot was taken: a cancel or a newer call already killed and reaped this one.
    Err("Process was cancelled".to_string())
}
// Quick read-only modes that run beside the tracked process instead of replacing it,
// so a background scan can't kill a TTS stage or an assistant call.
const UTILITY_MODES: &[&str] = &["extract_words", "extract_place_words", "get_furigana"];

#[tauri::command]
async fn run_python_utility(app: AppHandle, action: String, payload: String) -> Result<String, String> {
    if !UTILITY_MODES.contains(&action.as_str()) {
        return Err(format!("Not a utility mode: {action}"));
    }
    let mut cmd = python_command(&app)?;
    cmd.arg(&action).arg(&payload);
    let out = tauri::async_runtime::spawn_blocking(move || cmd.output())
        .await
        .map_err(|e| e.to_string())?
        .map_err(|e| e.to_string())?;
    if out.status.success() {
        Ok(String::from_utf8_lossy(&out.stdout).into_owned())
    } else {
        let err = String::from_utf8_lossy(&out.stderr).into_owned();
        Err(if err.is_empty() { "Process terminated".to_string() } else { err })
    }
}

#[tauri::command]
fn cancel_python_blueprint(state: State<'_, BlueprintState>) -> Result<String, String>{
    let mut lock = state.process.lock().map_err(|e| e.to_string())?;

    if let Some(mut child) = lock.take() {
        kill_tree(&mut child);
        let _ = child.wait();
        Ok("Cancelled".to_string())
    } else {
        Ok("No active process to cancel".to_string())
    }
}

#[tauri::command]
fn cancel_render(app: AppHandle, state: State<'_, BlueprintState>) -> Result<String, String> {
    state.render_cancelled.store(true, Ordering::SeqCst);
    let mut lock = state.render_process.lock().map_err(|e| e.to_string())?;
    if let Some(mut child) = lock.take() {
        kill_tree(&mut child);
        let _ = child.wait();
        let _ = app.emit("render-finish", "Cancelled");
        Ok("Cancelled".to_string())
    } else {
        Ok("No active process to cancel".to_string())
    }
}

#[tauri::command]
fn start_render(
    app: AppHandle,
    config_path: String,
    force: Option<bool>,
    state: State<'_, BlueprintState>,
) -> Result<String, String> {
    vc_runtime_guard()?;
    let mut command = python_command(&app)?;
    command.arg("full_pipeline").arg(&config_path);
    if force.unwrap_or(false) {
        // Bypasses the checkpoint/resume logic so every stage regenerates
        // from scratch, instead of skipping steps whose output already exists.
        command.arg("--force");
    }
    let mut child = command
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Failed to call Python: {}", e))?;

    let stdout = child.stdout.take().ok_or("Failed to capture stdout")?;
    let stderr = child.stderr.take().ok_or("Failed to capture stderr")?;

    state.render_cancelled.store(false, Ordering::SeqCst);

    // Track this child the same way run_python_blueprint's is tracked, so
    // an app exit (or a future cancel-render command) can find and kill it.
    // Kill off any previous render that's still stuck first.
    {
        let mut lock = state.render_process.lock().unwrap();
        if let Some(mut old_child) = lock.take() {
            kill_tree(&mut old_child);
            let _ = old_child.wait();
        }
        *lock = Some(child);
    }

    let app_stdout = app.clone();
    thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines() {
            if let Ok(line) = line {
                let _ = app_stdout.emit("render-log", line);
            }
        }
    });

    let app_stderr = app.clone();
    thread::spawn(move || {
        let reader = BufReader::new(stderr);
        for line in reader.lines() {
            if let Ok(line) = line {
                let _ = app_stderr.emit("render-error", line);
            }
        }
    });

    thread::spawn(move || loop {
        let child_state = app.state::<BlueprintState>();
        let mut finished = None;

        if let Ok(mut lock) = child_state.render_process.lock() {
            if let Some(child) = lock.as_mut() {
                match child.try_wait() {
                    Ok(Some(status)) => {
                        lock.take();
                        finished = Some(status.success());
                    }
                    Ok(None) => {}
                    Err(_) => {
                        lock.take();
                        finished = Some(false);
                    }
                }
            } else {
                return;
            }
        }

        if let Some(success) = finished {
            let payload = if child_state.render_cancelled.load(Ordering::SeqCst) {
                "Cancelled"
            } else if success {
                "Success"
            } else {
                "Failed"
            };
            let _ = app.emit("render-finish", payload);
            return;
        }

        thread::sleep(Duration::from_millis(100));
    });

    Ok("Rendering".to_string())
}

fn is_ollama_running() -> bool {
    TcpStream::connect_timeout(
        &"127.0.0.1:11434".parse().unwrap(), 
        Duration::from_millis(500)
    ).is_ok()
}

// PATH first, then the build downloaded into the app's bin folder, then the per-user installer's folder.
fn ollama_candidates() -> Vec<std::path::PathBuf> {
    let mut found = vec![std::path::PathBuf::from("ollama")];
    found.push(runtime::get().bundled_ollama());
    if let Ok(local) = std::env::var("LOCALAPPDATA") {
        found.push(Path::new(&local).join("Programs").join("Ollama").join("ollama.exe"));
    }
    found
}

#[tauri::command(async)]
fn wake_up_ollama() -> Result<String, String> {
    if is_ollama_running() {
        return Ok("Ollama OK".to_string());
    }

    let mut last_error = String::new();
    for exe in ollama_candidates() {
        if exe.components().count() > 1 && !exe.exists() {
            continue;
        }
        let mut serve = Command::new(&exe);
        runtime::hide_window(&mut serve);
        let spawned = serve
            .env("OLLAMA_ORIGINS", "*")
            .arg("serve")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn();
        match spawned {
            Ok(_) => return Ok("Ollama server started.".to_string()),
            Err(e) => last_error = e.to_string(),
        }
    }
    Err(format!("Ollama is not installed or could not be started ({})", last_error))
}

#[tauri::command]
async fn export_video(app: tauri::AppHandle, project_dir: String) -> Result<String, String> {
    println!("Starting video export for: {}", project_dir);

    let timeline_path = format!("{}/timeline.json", project_dir);

    let mut child = python_command(&app)?
        .arg("render_timeline")
        .arg(&timeline_path)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| e.to_string())?;

    // "EXPORT_PROGRESS <pct>" lines become export-progress events; the rest is kept for errors.
    let stderr = child.stderr.take().ok_or("Failed to capture stderr")?;
    let app_progress = app.clone();
    let stderr_reader = thread::spawn(move || {
        let mut rest = String::new();
        for line in BufReader::new(stderr).lines().map_while(Result::ok) {
            match line.strip_prefix("EXPORT_PROGRESS ").and_then(|p| p.trim().parse::<f64>().ok()) {
                Some(pct) => {
                    let _ = app_progress.emit("export-progress", pct);
                }
                None => {
                    rest.push_str(&line);
                    rest.push('\n');
                }
            }
        }
        rest
    });

    let output = child.wait_with_output().map_err(|e| e.to_string())?;
    let err = stderr_reader.join().unwrap_or_default();

    let stdout = String::from_utf8_lossy(&output.stdout).into_owned();
    if output.status.success() {
        app.emit("render-complete", ()).map_err(|e| e.to_string())?;
        // main.py's last stdout line is the JSON-encoded path of the exported video.
        let last = stdout.lines().rev().find(|l| !l.trim().is_empty()).unwrap_or("");
        Ok(last.trim().trim_matches('"').replace("\\\\", "\\"))
    } else {
        // main.py prints its failure as JSON on stdout; stderr only carries progress text.
        Err(format!("{}
{}", stdout.trim(), err.trim()).trim().to_string())
    }
}

#[tauri::command]
async fn copy_asset_file(source_path: String, target_dir: String) -> Result<String, String> {
    let source = Path::new(&source_path);
    
    let file_name = source.file_name().ok_or("Invalid file name")?;
    
    let target = Path::new(&target_dir).join(file_name);
    
    if let Err(e) = fs::create_dir_all(&target_dir) {
        return Err(format!("Failed to create directory: {}", e));
    }

    match fs::copy(&source, &target) {
        Ok(_) => Ok(target.to_string_lossy().to_string()),
        Err(e) => Err(format!("Failed to copy file: {}", e)),
    }
}

#[tauri::command(async)]
fn open_in_explorer(path: String) -> Result<(), String> {
    let p = std::path::Path::new(&path);
    #[cfg(target_os = "windows")]
    {
        let mut cmd = std::process::Command::new("explorer");
        if p.is_file() {
            cmd.arg("/select,").arg(&path);
        } else {
            cmd.arg(&path);
        }
        cmd.spawn().map_err(|e| e.to_string())?;
    }
    #[cfg(target_os = "macos")]
    {
        let mut cmd = std::process::Command::new("open");
        if p.is_file() {
            cmd.arg("-R").arg(&path);
        } else {
            cmd.arg(&path);
        }
        cmd.spawn().map_err(|e| e.to_string())?;
    }
    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        std::process::Command::new("xdg-open")
            .arg(&path)
            .spawn()
            .map_err(|e| e.to_string())?;
    }

    Ok(())
}


/// Downloads Microsoft's Visual C++ redistributable and runs it; Windows shows its own permission prompt (UAC).
/// Done here, not in Python: a clean PC may need it before the Python tools exist.
#[tauri::command]
async fn install_vc_runtime() -> Result<(), String> {
    if runtime::vc_runtime_present() {
        return Ok(());
    }
    let script = r#"$ErrorActionPreference = 'Stop'
$f = Join-Path $env:TEMP 'navivi_vc_redist.x64.exe'
Invoke-WebRequest 'https://aka.ms/vs/17/release/vc_redist.x64.exe' -OutFile $f -UseBasicParsing
$p = Start-Process $f -ArgumentList '/install','/quiet','/norestart' -Verb RunAs -Wait -PassThru
Remove-Item $f -Force -ErrorAction SilentlyContinue
exit $p.ExitCode"#;
    let output = tauri::async_runtime::spawn_blocking(move || {
        let mut cmd = Command::new("powershell");
        runtime::hide_window(&mut cmd);
        cmd.args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script]).output()
    })
    .await
    .map_err(|e| e.to_string())?
    .map_err(|e| e.to_string())?;
    // 1638: a newer one is already there; 3010: installed, restart pending.
    let code = output.status.code().unwrap_or(-1);
    if matches!(code, 0 | 1638 | 3010) || runtime::vc_runtime_present() {
        Ok(())
    } else {
        Err(format!("The Visual C++ runtime was not installed (exit {code}). {}", String::from_utf8_lossy(&output.stderr).trim()))
    }
}

#[tauri::command]
async fn convert_gps_to_gpx(input_path: String, input_format: String) -> Result<String, String> {
    vc_runtime_guard()?;
    let mut gpsbabel = Command::new(runtime::get().gpsbabel());
    runtime::hide_window(&mut gpsbabel);
    let output = gpsbabel
        .arg("-i")
        .arg(&input_format)
        .arg("-f")
        .arg(&input_path)
        .arg("-o")
        .arg("gpx")
        .arg("-F")
        .arg("-")
        .output()
        .map_err(|e| e.to_string())?;

    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).into_owned())
    } else {
        let err = String::from_utf8_lossy(&output.stderr).into_owned();
        if err.is_empty() {
            Err("gpsbabel failed without error output. Is it installed?".to_string())
        } else {
            Err(err)
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        // The frontend's Ollama calls (src/services/ollamaApi.ts) go through
        // @tauri-apps/plugin-http; without this they fail with "plugin http not found".
        .plugin(tauri_plugin_http::init())
        // Opens a provider's "get an API key" page in the browser (Settings > AI models).
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            runtime::init(runtime::Layout {
                dev_script_exists: runtime::running_from_repo(),
                resource_dir: app.path().resource_dir().ok().map(runtime::clean_path),
                local_data_dir: app.path().app_local_data_dir().ok().map(runtime::clean_path),
            });
            let dir = app.path().app_data_dir()?;
            fs::create_dir_all(&dir)?;
            let conn = db::open(&dir.join("navivi.db"))?;
            app.manage(db::DbState(Mutex::new(conn)));
            app.manage(StartedAt(std::time::Instant::now()));
            // If the page never reports in (a crash while loading), don't leave the user on the splash.
            let handle = app.handle().clone();
            thread::spawn(move || {
                thread::sleep(SPLASH_GIVE_UP);
                reveal_main(&handle);
            });
            Ok(())
        })
        .manage(oauth::OauthListener::default())
        .manage(BlueprintState {
            process: Mutex::new(None),
            render_process: Mutex::new(None),
            render_cancelled: AtomicBool::new(false),
        })
        .invoke_handler(tauri::generate_handler![
            run_python_blueprint,
            run_python_utility,
            cancel_python_blueprint,
            cancel_render,
            start_render,
            wake_up_ollama,
            export_video,
            app_ready,
            copy_asset_file,
            open_in_explorer,
            runtime::runtime_status,
            install_vc_runtime,
            runtime::runtime_install,
            oauth::oauth_listen_start,
            oauth::oauth_listen_wait,
            oauth::oauth_listen_cancel,
            secrets::secret_set,
            secrets::secret_get,
            secrets::secret_delete,
            project_files::export_project_archive,
            project_files::tidy_project_folder,
            project_files::duplicate_project_folder,
            unzip_project,
            convert_gps_to_gpx,
            db::commands::project_create,
            db::commands::project_upsert,
            db::commands::project_get,
            db::commands::project_get_by_dir,
            db::commands::project_list,
            db::commands::project_update,
            db::commands::project_touch_opened,
            db::commands::project_forget_opened,
            db::commands::project_delete,
            db::commands::project_restore,
            db::commands::project_purge,
            db::commands::project_import_legacy,
            db::commands::settings_get,
            db::commands::settings_put,
            db::commands::settings_patch,
            db::commands::settings_delete,
            db::commands::version_create,
            db::commands::version_list,
            db::commands::version_get,
            db::commands::version_rename,
            db::commands::version_delete,
            db::commands::version_delete_all,
            db::commands::route_cache_get_all,
            db::commands::route_cache_get,
            db::commands::route_cache_put,
            db::commands::route_cache_put_many,
            db::commands::route_cache_replace,
            db::commands::route_cache_delete,
            db::commands::route_cache_prune,
            db::commands::route_cache_clear,
            db::commands::app_setting_get,
            db::commands::app_setting_set,
            db::commands::app_setting_delete,
            db::commands::app_setting_list,
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            // A force-closed window (or OS shutdown) previously left any
            // running Python worker  Eand whatever bundled server it had
            // itself spawned (TTS/ComfyUI)  Erunning with nothing left to
            // supervise it. Kill whatever this app is still tracking on exit.
            if let tauri::RunEvent::ExitRequested { .. } = event {
                if let Some(state) = app_handle.try_state::<BlueprintState>() {
                    kill_tracked_children(&state);
                }
            }
        });
}

use std::io::Read;
use zip::ZipArchive;

#[tauri::command]
async fn unzip_project(source_file: String, dest_dir: String) -> Result<(), String> {
    let file = fs::File::open(&source_file).map_err(|e| e.to_string())?;
    let mut archive = ZipArchive::new(file).map_err(|e| e.to_string())?;

    for i in 0..archive.len() {
        let mut file = archive.by_index(i).map_err(|e| e.to_string())?;
        let outpath = match file.enclosed_name() {
            Some(path) => Path::new(&dest_dir).join(path),
            None => continue,
        };

        if (*file.name()).ends_with('/') {
            fs::create_dir_all(&outpath).map_err(|e| e.to_string())?;
        } else {
            if let Some(p) = outpath.parent() {
                if !p.exists() {
                    fs::create_dir_all(p).map_err(|e| e.to_string())?;
                }
            }
            let mut outfile = fs::File::create(&outpath).map_err(|e| e.to_string())?;
            std::io::copy(&mut file, &mut outfile).map_err(|e| e.to_string())?;
        }
    }
    Ok(())
}

#[cfg(all(test, target_os = "windows"))]
mod tests {
    use super::*;
    use std::collections::HashSet;

    fn ping_pids() -> HashSet<String> {
        let out = Command::new("tasklist")
            .args(["/FI", "IMAGENAME eq PING.EXE", "/FO", "CSV", "/NH"])
            .output()
            .expect("tasklist");
        String::from_utf8_lossy(&out.stdout)
            .lines()
            .filter_map(|l| l.split(',').nth(1).map(|p| p.trim_matches('"').to_string()))
            .filter(|p| p.chars().all(|c| c.is_ascii_digit()) && !p.is_empty())
            .collect()
    }

    #[test]
    fn kill_tree_also_ends_the_grandchildren() {
        let before = ping_pids();
        let mut child = Command::new("cmd")
            .args(["/C", "ping -n 60 127.0.0.1 >nul"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("spawn");
        thread::sleep(Duration::from_millis(1500));
        let started: Vec<String> = ping_pids().difference(&before).cloned().collect();
        assert_eq!(started.len(), 1, "the ping grandchild should be running");

        kill_tree(&mut child);
        let _ = child.wait();
        thread::sleep(Duration::from_millis(1000));
        assert!(!ping_pids().contains(&started[0]), "the grandchild survived");
    }
}
