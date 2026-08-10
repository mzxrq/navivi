use std::fs;
use std::path::Path;
use std::process::Command;

#[tauri::command]
fn store_file_in_backend(source_path: String, filename: String) -> Result<String, String> {
    let target_dir = Path::new("src-python/data/inputs/gpsdata/rawdata");
    if !target_dir.exists() {
        fs::create_dir_all(target_dir).map_err(|e| e.to_string())?;
    }

    let destination_path = target_dir.join(&filename);

    match fs::copy(&source_path, &destination_path) {
        Ok(_) => Ok(destination_path.to_string_lossy().into_owned()),
        Err(e) => Err(format!("Failed to copy file: {}", e)),
    }
}

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
            store_file_in_backend,
            trigger_render_pipeline
        ])

        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}