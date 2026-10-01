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

struct BlueprintState {
    process: Mutex<Option<Child>>,
    render_process: Mutex<Option<Child>>,
    render_cancelled: AtomicBool,
}

fn kill_tracked_children(state: &BlueprintState) {
    if let Ok(mut lock) = state.process.lock() {
        if let Some(mut child) = lock.take() {
            let _ = child.kill();
        }
    }
    if let Ok(mut lock) = state.render_process.lock() {
        if let Some(mut child) = lock.take() {
            let _ = child.kill();
        }
    }
}


#[tauri::command]
async fn run_python_blueprint(
    action: String, 
    payload: String,
    state: State<'_, BlueprintState>
) -> Result<String, String> {
    
    // Spawn instead of output()
    let mut child = Command::new("python")
        .env("PYTHONIOENCODING", "utf-8")
        .arg("src-python/main.py")
        .arg(&action)
        .arg(&payload)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| e.to_string())?;

    // Extract the pipes before moving the child to the state
    let mut stdout = child.stdout.take().ok_or("Failed to capture stdout")?;
    let mut stderr = child.stderr.take().ok_or("Failed to capture stderr")?;

    // 2. Lock the Mutex and store the child process safely
    {
        let mut lock = state.process.lock().unwrap();
        // If there's an existing process stuck, kill it before starting a new one
        if let Some(mut old_child) = lock.take() {
            let _ = old_child.kill();
            let _ = old_child.wait();
        }
        *lock = Some(child);
    }

    // 3. Read stderr on a separate thread to prevent OS pipe deadlocks
    let stderr_thread = thread::spawn(move || {
        let mut err_str = String::new();
        let _ = stderr.read_to_string(&mut err_str);
        err_str
    });

    // 4. Read stdout on the main task thread
    // This will naturally block here until the process finishes OR gets killed.
    let mut out_str = String::new();
    let _ = stdout.read_to_string(&mut out_str);

    let err_str = stderr_thread.join().unwrap_or_default();

    // 5. Streams are closed. Clean up and get the exit status.
    let mut lock = state.process.lock().unwrap();
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

    // If lock.take() was None, it means the cancel command already took it and reaped it!
    Err("Process was cancelled".to_string())
}
#[tauri::command]
fn cancel_python_blueprint(state: State<'_, BlueprintState>) -> Result<String, String>{
    let mut lock = state.process.lock().map_err(|e| e.to_string())?;

    if let Some(mut child) = lock.take() {
        let _ = child.kill();
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
        let _ = child.kill();
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
    let mut command = Command::new("python");
    command
        .env("PYTHONIOENCODING", "utf-8")
        .arg("src-python/main.py")
        .arg("full_pipeline")
        .arg(&config_path);
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
            let _ = old_child.kill();
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

#[tauri::command]
fn wake_up_ollama() -> Result<String, String> {
    if is_ollama_running() {
        return Ok("Ollama OK".to_string());
    }

    let result = Command::new("ollama")
        .env("OLLAMA_ORIGINS", "*")
        .arg("serve")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn();

    match result {
        Ok(_) => Ok("Ollama server started.".to_string()),
        Err(e) => Err(format!("Failed to start Ollama, is it installed? Error: {}", e)),
    }
}

#[tauri::command]
async fn export_video(app: tauri::AppHandle, project_dir: String) -> Result<String, String> {
    println!("Starting video export for: {}", project_dir);

    let timeline_path = format!("{}/timeline.json", project_dir);

    let output = std::process::Command::new("python")
        .env("PYTHONIOENCODING", "utf-8")
        .arg("src-python/main.py")
        .arg("render_timeline")
        .arg(&timeline_path)
        .output()
        .map_err(|e| e.to_string())?;

    let stdout = String::from_utf8_lossy(&output.stdout).into_owned();
    if output.status.success() {
        app.emit("render-complete", ()).map_err(|e| e.to_string())?;
        // main.py's last stdout line is the JSON-encoded path of the exported video.
        let last = stdout.lines().rev().find(|l| !l.trim().is_empty()).unwrap_or("");
        Ok(last.trim().trim_matches('"').replace("\\\\", "\\"))
    } else {
        // main.py prints its failure as JSON on stdout; stderr only carries progress text.
        let err = String::from_utf8_lossy(&output.stderr);
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

#[tauri::command]
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


#[tauri::command]
async fn convert_gps_to_gpx(input_path: String, input_format: String) -> Result<String, String> {
    let output = std::process::Command::new("gpsbabel")
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
        .setup(|app| {
            let dir = app.path().app_data_dir()?;
            fs::create_dir_all(&dir)?;
            let conn = db::open(&dir.join("navivi.db"))?;
            app.manage(db::DbState(Mutex::new(conn)));
            Ok(())
        })
        .manage(BlueprintState {
            process: Mutex::new(None),
            render_process: Mutex::new(None),
            render_cancelled: AtomicBool::new(false),
        })
        .invoke_handler(tauri::generate_handler![
            run_python_blueprint,
            cancel_python_blueprint,
            cancel_render,
            start_render,
            wake_up_ollama,
            export_video,
            copy_asset_file,
            open_in_explorer,
            zip_project,
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

use zip::ZipWriter;
use std::io::{Read, Write};
use walkdir::WalkDir;
use zip::ZipArchive;

#[tauri::command]
async fn zip_project(source_dir: String, dest_file: String) -> Result<(), String> {
    let path = Path::new(&dest_file);
    let file = fs::File::create(path).map_err(|e| e.to_string())?;
    let mut zip = ZipWriter::new(file);
    let options = zip::write::SimpleFileOptions::default().compression_method(zip::CompressionMethod::Stored);

    let walkdir = WalkDir::new(&source_dir);
    let it = walkdir.into_iter();

    for entry in it.filter_map(|e| e.ok()) {
        let path = entry.path();
        let name = path.strip_prefix(Path::new(&source_dir))
            .unwrap()
            .to_string_lossy()
            .into_owned()
            .replace("\\", "/");

        if name.is_empty() {
            continue;
        }

        if path.is_file() {
            zip.start_file(&name, options).map_err(|e| e.to_string())?;
            let mut f = fs::File::open(path).map_err(|e| e.to_string())?;
            let mut buffer = Vec::new();
            f.read_to_end(&mut buffer).map_err(|e| e.to_string())?;
            zip.write_all(&buffer).map_err(|e| e.to_string())?;
        } else if !name.is_empty() {
            zip.add_directory(&name, options).map_err(|e| e.to_string())?;
        }
    }
    zip.finish().map_err(|e| e.to_string())?;
    Ok(())
}

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
