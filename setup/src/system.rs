//! The Windows parts: language, running copies of the app, shortcuts, the Apps & features entry.

use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use winreg::enums::{HKEY_CURRENT_USER, KEY_ALL_ACCESS};
use winreg::RegKey;

const CREATE_NO_WINDOW: u32 = 0x0800_0000;
const DETACHED_PROCESS: u32 = 0x0000_0008;
const UNINSTALL_KEY: &str = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Navivi";

/// Whether the user's Windows display language is Japanese (the setup speaks Japanese then, English otherwise).
pub fn ui_is_japanese() -> bool {
    // SAFETY: a plain query with no arguments.
    let langid = unsafe { windows_sys::Win32::Globalization::GetUserDefaultUILanguage() };
    (langid & 0x3ff) == 0x11
}

pub fn local_app_data() -> PathBuf {
    std::env::var_os("LOCALAPPDATA").map(PathBuf::from).unwrap_or_else(|| PathBuf::from(r"C:\Users\Public"))
}

fn ps_quote(s: &str) -> String {
    format!("'{}'", s.replace('\'', "''"))
}

fn powershell(script: &str) -> Option<String> {
    let out = Command::new("powershell")
        .args(["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script])
        .creation_flags(CREATE_NO_WINDOW)
        .stdin(Stdio::null())
        .output()
        .ok()?;
    Some(String::from_utf8_lossy(&out.stdout).into_owned())
}

/// Process ids of `navivi.exe` running from `dir`.
pub fn running_instances(dir: &Path) -> Vec<u32> {
    let script = format!(
        "Get-CimInstance Win32_Process -Filter \"Name='navivi.exe'\" | Where-Object {{ $_.ExecutablePath -like ({} + '*') }} | ForEach-Object {{ $_.ProcessId }}",
        ps_quote(&dir.display().to_string())
    );
    powershell(&script)
        .unwrap_or_default()
        .lines()
        .filter_map(|l| l.trim().parse().ok())
        .collect()
}

pub fn stop_instances(pids: &[u32]) {
    for pid in pids {
        let _ = Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .creation_flags(CREATE_NO_WINDOW)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
}

/// Shortcuts to `target` on the desktop and/or in the Start menu.
pub fn create_shortcuts(name: &str, target: &Path, workdir: &Path, desktop: bool, start_menu: bool) {
    let script = format!(
        "$s = New-Object -ComObject WScript.Shell; \
         function Make($folder) {{ $l = $s.CreateShortcut((Join-Path $folder ({n} + '.lnk'))); $l.TargetPath = {t}; $l.WorkingDirectory = {w}; $l.IconLocation = {t}; $l.Save() }}; \
         if ({d}) {{ Make ([Environment]::GetFolderPath('Desktop')) }}; \
         if ({m}) {{ Make ([Environment]::GetFolderPath('Programs')) }}",
        n = ps_quote(name),
        t = ps_quote(&target.display().to_string()),
        w = ps_quote(&workdir.display().to_string()),
        d = if desktop { "$true" } else { "$false" },
        m = if start_menu { "$true" } else { "$false" },
    );
    let _ = powershell(&script);
}

pub fn remove_shortcuts(name: &str) {
    let script = format!(
        "foreach ($f in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {{ Remove-Item -LiteralPath (Join-Path $f ({} + '.lnk')) -Force -ErrorAction SilentlyContinue }}",
        ps_quote(name)
    );
    let _ = powershell(&script);
}

/// What Apps & features shows for the app: name, version, where it lives and how to remove it.
pub fn uninstall_entry_values(name: &str, version: &str, dir: &Path, exe: &Path, size_kb: u32) -> Vec<(&'static str, RegValue)> {
    let uninstaller = dir.join("uninstall.exe");
    vec![
        ("DisplayName", RegValue::Text(name.to_string())),
        ("DisplayVersion", RegValue::Text(version.to_string())),
        ("InstallLocation", RegValue::Text(dir.display().to_string())),
        ("DisplayIcon", RegValue::Text(exe.display().to_string())),
        ("UninstallString", RegValue::Text(format!("\"{}\" --uninstall", uninstaller.display()))),
        ("QuietUninstallString", RegValue::Text(format!("\"{}\" --uninstall --silent", uninstaller.display()))),
        ("EstimatedSize", RegValue::Number(size_kb)),
        ("NoModify", RegValue::Number(1)),
        ("NoRepair", RegValue::Number(1)),
    ]
}

#[derive(Debug, PartialEq)]
pub enum RegValue {
    Text(String),
    Number(u32),
}

pub fn write_uninstall_entry(values: &[(&'static str, RegValue)]) -> Result<(), String> {
    let (key, _) = RegKey::predef(HKEY_CURRENT_USER).create_subkey(UNINSTALL_KEY).map_err(|e| e.to_string())?;
    for (name, value) in values {
        match value {
            RegValue::Text(s) => key.set_value(name, s),
            RegValue::Number(n) => key.set_value(name, n),
        }
        .map_err(|e| e.to_string())?;
    }
    Ok(())
}

pub fn remove_uninstall_entry() {
    let _ = RegKey::predef(HKEY_CURRENT_USER).delete_subkey_all(UNINSTALL_KEY);
}

/// Where the previous install is, if there is one (so an update goes to the same place).
pub fn previous_install_dir() -> Option<PathBuf> {
    let key = RegKey::predef(HKEY_CURRENT_USER).open_subkey_with_flags(UNINSTALL_KEY, KEY_ALL_ACCESS).ok()?;
    let dir: String = key.get_value("InstallLocation").ok()?;
    Some(PathBuf::from(dir)).filter(|p| p.exists())
}

/// Starts a program that outlives this one.
pub fn spawn_detached(exe: &Path, args: &[&str], cwd: Option<&Path>) {
    let mut cmd = Command::new(exe);
    cmd.args(args).creation_flags(DETACHED_PROCESS | CREATE_NO_WINDOW).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
    if let Some(cwd) = cwd {
        cmd.current_dir(cwd);
    }
    let _ = cmd.spawn();
}

/// Deletes `path` (a file or folder) a moment after this process has exited.
pub fn delete_after_exit(path: &Path) {
    let p = path.display().to_string();
    // raw_arg: cmd does not understand the backslash-escaped quotes Rust would otherwise put around the path.
    let _ = Command::new("cmd")
        .raw_arg(format!("/C ping 127.0.0.1 -n 3 >nul & rmdir /s /q \"{p}\" 2>nul & del /f /q \"{p}\" 2>nul"))
        .creation_flags(DETACHED_PROCESS | CREATE_NO_WINDOW)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_apps_and_features_entry_points_at_the_uninstaller_and_the_app() {
        let values = uninstall_entry_values("Navivi", "1.0.0", Path::new(r"C:\Apps\Navivi"), Path::new(r"C:\Apps\Navivi\navivi.exe"), 321_000);
        let get = |name: &str| values.iter().find(|(n, _)| *n == name).map(|(_, v)| v);
        assert_eq!(get("UninstallString"), Some(&RegValue::Text(r#""C:\Apps\Navivi\uninstall.exe" --uninstall"#.into())));
        assert_eq!(get("QuietUninstallString"), Some(&RegValue::Text(r#""C:\Apps\Navivi\uninstall.exe" --uninstall --silent"#.into())));
        assert_eq!(get("InstallLocation"), Some(&RegValue::Text(r"C:\Apps\Navivi".into())));
        assert_eq!(get("EstimatedSize"), Some(&RegValue::Number(321_000)));
    }

    #[test]
    fn powershell_strings_survive_an_apostrophe_in_a_path() {
        assert_eq!(ps_quote(r"C:\Users\O'Brien\Navivi"), r"'C:\Users\O''Brien\Navivi'");
    }
}
