use std::fs;
use std::process::Command;

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

// #[tauri::command]
// async fn store_file_in_backend(source_path: String, payload: String) -> Result<String, String> {
//     let output = Command::new("python")
//         .arg("src-python/services/filehandler.py")
//         .arg(&source_path)
//         .output()
//         .map_err(|e| format!("Failed to call file handler: {}", e))?;

//     if output.status.success() {
//         // grab printed path from terminal
//         let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
//         let final_path = stdout.lines().last().unwrap_or("").to_string();

//         if final_path.is_empty() {
//             Err("Python file handler failed to return a path.".into())
//         } else {
//             Ok(final_path)
//         }
//     } else {
//         let stderr = String::from_utf8_lossy(&output.stderr).to_string();
//         Err(format!("Python script crashed: {}", stdeer))
//     }
// }

#[tauri::command]
fn trigger_render_pipeline(payload: String) -> Result<String, String> {
    let config_path = "src-python/data/job_config.json";
    
    // write json config to drive
    fs::write(config_path, &payload)
        .map_err(|e| format!("Failed to save config: {}", e))?;
    // call bg process
    let output = Command::new("python")
        .arg("src-python/main.py")
        .arg("--config")
        .arg(config_path)
        .output()
        .map_err(|e| format!("Failed to wake up Python: {}", e))?;
    // error handle exception (check if render success or not)
    if output.status.success() {
        let success_logs = String::from_utf8_lossy(&output.stdout).to_string();
        Ok(format!("Render Complete.\nLogs:\n{}", success_logs))
    } else {
        let error_logs = String::from_utf8_lossy(&output.stderr).to_string();
        Err(format!("Engine Crashed:\n{}", error_logs))
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())

        .invoke_handler(tauri::generate_handler![
            run_python_blueprint,
            trigger_render_pipeline
        ])

        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}