use std::process::{Command, Stdio};
use std::io::{BufRead, BufReader};
use std::thread;
use tauri::{AppHandle, Emitter};

#[tauri::command]
async fn run_python_blueprint(action: String, payload: String) -> Result<String, String> {
    let output = Command::new("python")
        .env("PYTHONIOENCODING", "utf-8")
        .arg("src-python/main.py")
        .arg(&action)
        .arg(&payload)
        .output();
    match output {
        Ok(res) => {
            if res.status.success() {
                Ok(String::from_utf8_lossy(&res.stdout).to_string())
            } else {
                Err(String::from_utf8_lossy(&res.stderr).to_string())
            }
        }
        Err(e) => Err(e.to_string())
    }
}

#[tauri::command]
fn start_render(app: AppHandle, config_path: String) -> Result<String, String> {
    let mut child = Command::new("python")
        .arg("src-python/main.py")
        .arg("--config")
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())

        .invoke_handler(tauri::generate_handler![
            run_python_blueprint,
            start_render
        ])

        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}