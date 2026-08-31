use std::net::TcpStream;
use std::process::{Child, Command, Stdio};
use std::io::{BufRead, BufReader, Read};
use std::sync::Mutex;
use std::{thread};
use std::time::Duration;
use tauri::{AppHandle, Emitter, State};
struct BlueprintState {
    process: Mutex<Option<Child>>,
}

#[tauri::command]
async fn run_python_blueprint(
    action: String, 
    payload: String,
    state: State<'_, BlueprintState> // Inject our state here
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
fn start_render(app: AppHandle, config_path: String) -> Result<String, String> {
    let mut child = Command::new("python")
        .env("PYTHONIOENCODING", "utf-8")
        .arg("src-python/main.py")
        .arg("full_pipeline")
        .arg(&config_path)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Failed to call Python: {}", e))?;

    let stdout = child.stdout.take().ok_or("Failed to capture stdout")?;
    let stderr = child.stderr.take().ok_or("Failed to capture stderr")?;

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

    thread::spawn(move || {
        let status = child.wait().expect("Failed to wait on child");
        if status.success() {
            let _ = app.emit("render-finish", "Success");
        } else {
            let _ = app.emit("render-finish", "Failed");
        }
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
async fn export_video(app: tauri::AppHandle, project_dir: String) -> Result<(), String> {
    println!("Starting video export for: {}", project_dir);

    // Build the path to timeline.json that React just saved
    let timeline_path = format!("{}/timeline.json", project_dir);

    // Call Dev 1's specific command registry handler
    let output = std::process::Command::new("python")
        .arg("src-python/main.py")
        .arg("render_timeline") 
        .arg(&timeline_path)    
        .output()
        .map_err(|e| e.to_string())?;

    if output.status.success() {
        // TAURI V2 SYNTAX: Broadcast on our custom channel so React knows it is done!
        app.emit("render-complete", ()).map_err(|e| e.to_string())?;
        Ok(())
    } else {
        let err = String::from_utf8_lossy(&output.stderr).into_owned();
        Err(err)
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .manage(BlueprintState {
            process: Mutex::new(None),
        })
        .invoke_handler(tauri::generate_handler![
            run_python_blueprint,
            cancel_python_blueprint,
            start_render,
            wake_up_ollama,
            export_video,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}