//! The Windows parts: language, running copies of the app, shortcuts, the Apps & features entry.

use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use winreg::enums::{HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE, KEY_ALL_ACCESS};
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

/// `%APPDATA%`, where the app keeps its database (settings, project list, version history).
pub fn roaming_app_data() -> PathBuf {
    std::env::var_os("APPDATA").map(PathBuf::from).unwrap_or_else(|| PathBuf::from(r"C:\Users\Public"))
}

/// The user's Documents folder, which may be redirected (OneDrive), as the app sees it.
pub fn documents_dir() -> PathBuf {
    powershell("[Environment]::GetFolderPath('MyDocuments')")
        .map(|s| PathBuf::from(s.trim()))
        .filter(|p| p.is_absolute())
        .or_else(|| std::env::var_os("USERPROFILE").map(|p| PathBuf::from(p).join("Documents")))
        .unwrap_or_else(|| PathBuf::from(r"C:\Users\Public\Documents"))
}

/// The AI provider keys the app saved in Windows Credential Manager (service "Navivi", user `ai-key:<provider>`; the keyring
/// crate names the credential `<user>.<service>`). Best effort: a key that is not there is not an error.
pub fn delete_saved_keys() {
    for provider in ["anthropic", "openai", "gemini", "openrouter", "custom"] {
        let _ = Command::new("cmdkey")
            .arg(format!("/delete:ai-key:{provider}.Navivi"))
            .creation_flags(CREATE_NO_WINDOW)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
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

/// Whether the Microsoft Visual C++ 2015-2022 runtime (x64) is installed. The app itself does not need it (its runtime is built in),
/// but the PyTorch behind the voices and the moving videos loads msvcp140.dll / vcruntime140.dll from the system.
pub fn vc_runtime_installed() -> bool {
    RegKey::predef(HKEY_LOCAL_MACHINE)
        .open_subkey(r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64")
        .and_then(|key| key.get_value::<u32, _>("Installed"))
        .map(|installed| installed == 1)
        .unwrap_or(false)
}

/// Downloads Microsoft's redistributable and runs it quietly (Windows asks for permission). Exit codes 0, 1638 (a newer one is
/// already there) and 3010 (done, restart pending) all mean it is in place.
pub fn install_vc_runtime() -> Result<(), String> {
    let script = "$ErrorActionPreference = 'Stop';         [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12;         $f = Join-Path $env:TEMP 'navivi_vc_redist.x64.exe';         Invoke-WebRequest -UseBasicParsing 'https://aka.ms/vs/17/release/vc_redist.x64.exe' -OutFile $f;         $p = Start-Process -FilePath $f -ArgumentList '/install','/quiet','/norestart' -Verb RunAs -Wait -PassThru;         Remove-Item $f -ErrorAction SilentlyContinue;         $p.ExitCode";
    let out = Command::new("powershell")
        .args(["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script])
        .creation_flags(CREATE_NO_WINDOW)
        .stdin(Stdio::null())
        .output()
        .map_err(|e| e.to_string())?;
    let text = String::from_utf8_lossy(&out.stdout);
    match text.trim().lines().last().and_then(|l| l.trim().parse::<i32>().ok()) {
        Some(0 | 1638 | 3010) => Ok(()),
        Some(code) => Err(format!("the Visual C++ runtime setup ended with code {code}")),
        None => Err(String::from_utf8_lossy(&out.stderr).trim().to_string()),
    }
}

/// `dir` as a prefix that matches only paths inside it: with a trailing backslash, `...\Navivi` no longer matches `...\Navivi-dev\...`.
/// Compared with StartsWith, not -like, so `[`, `]` and `*` in a folder name are plain characters.
fn inside_prefix(dir: &Path) -> String {
    let text = dir.display().to_string();
    format!("{}\\", text.trim_end_matches('\\'))
}

/// Process ids of `navivi.exe` running from `dir`.
pub fn running_instances(dir: &Path) -> Vec<u32> {
    let script = format!(
        "Get-CimInstance Win32_Process -Filter \"Name='navivi.exe'\" | Where-Object {{ $_.ExecutablePath -and $_.ExecutablePath.StartsWith({}, [StringComparison]::OrdinalIgnoreCase) }} | ForEach-Object {{ $_.ProcessId }}",
        ps_quote(&inside_prefix(dir))
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

/// Removes the shortcuts called `name` that point into `dir`; one that leads to another install of the app is not ours to delete.
pub fn remove_shortcuts(name: &str, dir: &Path) {
    let script = format!(
        "$s = New-Object -ComObject WScript.Shell; \
         foreach ($f in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {{ \
           $p = Join-Path $f ({n} + '.lnk'); \
           if (Test-Path -LiteralPath $p) {{ if ($s.CreateShortcut($p).TargetPath.StartsWith({d}, [StringComparison]::OrdinalIgnoreCase)) {{ Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue }} }} }}",
        n = ps_quote(name),
        d = ps_quote(&inside_prefix(dir)),
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

/// Whether `location` (as stored in the registry, maybe quoted or with a trailing slash) is the folder `dir`.
pub fn same_folder(location: &str, dir: &Path) -> bool {
    let norm = |s: &str| s.trim().trim_matches('"').trim_end_matches(['\\', '/']).replace('/', "\\").to_lowercase();
    norm(location) == norm(&dir.display().to_string())
}

/// Removes the Apps & features entry, but only when it describes the install in `dir` (the NSIS installer uses the same key).
pub fn remove_uninstall_entry(dir: &Path) {
    let root = RegKey::predef(HKEY_CURRENT_USER);
    let Ok(key) = root.open_subkey(UNINSTALL_KEY) else { return };
    let location: String = key.get_value("InstallLocation").unwrap_or_default();
    drop(key);
    if same_folder(&location, dir) {
        let _ = root.delete_subkey_all(UNINSTALL_KEY);
    }
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
    fn a_registry_location_matches_its_folder_however_it_is_written() {
        let dir = Path::new(r"C:\Users\u\AppData\Local\Navivi");
        assert!(same_folder(r#""C:\Users\u\AppData\Local\Navivi""#, dir));
        assert!(same_folder(r"c:\users\U\appdata\local\navivi\", dir));
        assert!(!same_folder(r"C:\Users\u\AppData\Local\Programs\Navivi", dir));
        assert!(!same_folder("", dir));
    }

    #[test]
    fn powershell_strings_survive_an_apostrophe_in_a_path() {
        assert_eq!(ps_quote(r"C:\Users\O'Brien\Navivi"), r"'C:\Users\O''Brien\Navivi'");
    }
}
