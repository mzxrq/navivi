//! Installing and removing: the steps shared by the window and by `--silent`.

use crate::payload::{self, Manifest, Payload, FILE_LIST};
use crate::system;
use serde::Serialize;
use std::fs;
use std::path::{Path, PathBuf};

pub const MARKER: &str = FILE_LIST;
pub const UNINSTALLER: &str = "uninstall.exe";

#[derive(Debug, Clone)]
pub struct Options {
    pub dir: PathBuf,
    pub desktop: bool,
    pub start_menu: bool,
    pub launch: bool,
    /// Close a running copy of the app instead of stopping to ask.
    pub close_running: bool,
}

/// What the window shows while this runs.
#[derive(Debug, Clone, Serialize)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum Event {
    Progress { pct: f64, file: String },
    Step { name: &'static str },
}

pub fn default_dir() -> PathBuf {
    system::previous_install_dir().unwrap_or_else(|| system::local_app_data().join("Programs").join("Navivi"))
}

/// The folder to install into: the one chosen, or a `Navivi` folder inside it when it already holds something else, so the
/// uninstaller and updates can never touch someone's other files.
pub fn resolve_dir(chosen: &Path) -> PathBuf {
    let ours = chosen.join(MARKER).exists();
    let empty = fs::read_dir(chosen).map(|mut d| d.next().is_none()).unwrap_or(true);
    if ours || empty || chosen.file_name().is_some_and(|n| n.eq_ignore_ascii_case("Navivi")) {
        chosen.to_path_buf()
    } else {
        chosen.join("Navivi")
    }
}

/// Refuses folders no install belongs in: a drive root or a Windows system folder.
pub fn check_dir(dir: &Path) -> Result<(), String> {
    if !dir.is_absolute() || dir.parent().is_none() {
        return Err("Choose a folder, not a whole drive.".into());
    }
    let lower = dir.display().to_string().to_lowercase();
    for blocked in [r"\windows", r"\program files", r"\program files (x86)"] {
        let marker = format!(":{blocked}");
        if lower.contains(&marker) && !lower.contains(r"\appdata\") {
            return Err("Choose a folder you can write to, such as the default one.".into());
        }
    }
    Ok(())
}

pub fn install(opts: &Options, payload: &Payload, mut emit: impl FnMut(Event)) -> Result<Manifest, String> {
    check_dir(&opts.dir)?;
    let mut archive = payload.archive()?;
    let manifest = payload::read_manifest(&mut archive)?;

    emit(Event::Step { name: "closing" });
    let running = system::running_instances(&opts.dir);
    if !running.is_empty() {
        if !opts.close_running {
            return Err("RUNNING".into());
        }
        system::stop_instances(&running);
        std::thread::sleep(std::time::Duration::from_millis(1200));
    }

    emit(Event::Step { name: "copying" });
    fs::create_dir_all(&opts.dir).map_err(|e| format!("{}: {e}", opts.dir.display()))?;
    let mut last_pct = -1.0;
    let written = payload::extract(&mut archive, &opts.dir, |done, total, file| {
        let pct = if total == 0 { 100.0 } else { (done as f64 / total as f64 * 1000.0).round() / 10.0 };
        if pct != last_pct {
            last_pct = pct;
            emit(Event::Progress { pct, file: file.to_string() });
        }
    })?;

    emit(Event::Step { name: "finishing" });
    let mut list = written.join("\n");
    list.push('\n');
    fs::write(opts.dir.join(FILE_LIST), list).map_err(|e| e.to_string())?;
    write_uninstaller(&payload.path, payload.start, &opts.dir.join(UNINSTALLER))?;

    let exe = opts.dir.join(&manifest.exe);
    if opts.desktop || opts.start_menu {
        system::create_shortcuts(&manifest.name, &exe, &opts.dir, opts.desktop, opts.start_menu);
    }
    let size_kb = (dir_size(&opts.dir) / 1024).min(u32::MAX as u64) as u32;
    system::write_uninstall_entry(&system::uninstall_entry_values(&manifest.name, &manifest.version, &opts.dir, &exe, size_kb))?;
    Ok(manifest)
}

/// The uninstaller is this exe without the payload.
fn write_uninstaller(setup_exe: &Path, plain_len: u64, to: &Path) -> Result<(), String> {
    use std::io::Read;
    let mut bytes = Vec::with_capacity(plain_len as usize);
    fs::File::open(setup_exe).map_err(|e| e.to_string())?.take(plain_len).read_to_end(&mut bytes).map_err(|e| e.to_string())?;
    fs::write(to, bytes).map_err(|e| format!("{}: {e}", to.display()))
}

pub fn dir_size(dir: &Path) -> u64 {
    let mut total = 0;
    if let Ok(entries) = fs::read_dir(dir) {
        for entry in entries.flatten() {
            match entry.metadata() {
                Ok(m) if m.is_dir() => total += dir_size(&entry.path()),
                Ok(m) => total += m.len(),
                Err(_) => {}
            }
        }
    }
    total
}

/// What the first-run setup downloads into the user's local data folder (see src-tauri/src/runtime.rs).
pub fn data_dirs() -> Vec<PathBuf> {
    let base = system::local_app_data().join("navivi");
    vec![base.join("runtime"), base.join("bin"), base.join("downloads")]
}

pub fn data_size() -> u64 {
    data_dirs().iter().map(|d| dir_size(d)).sum()
}

/// A fresh .exe can be held for a moment by a virus scanner or a process that is still closing, so a locked file gets a few more tries.
fn remove_file_retrying(path: &Path) {
    for attempt in 0..6 {
        match fs::remove_file(path) {
            Ok(()) => return,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return,
            Err(_) if attempt < 5 => std::thread::sleep(std::time::Duration::from_millis(400)),
            Err(_) => {}
        }
    }
}

/// Removes the files the installer listed, then any folders that are left empty. Anything else in the folder stays.
pub fn remove_installed_files(dir: &Path) -> Result<(), String> {
    let list = fs::read_to_string(dir.join(FILE_LIST)).unwrap_or_default();
    let mut folders = std::collections::BTreeSet::new();
    for rel in list.lines().filter(|l| !l.trim().is_empty()) {
        let Some(path) = payload::safe_join(dir, rel) else { continue };
        let mut parent = if rel.ends_with('/') {
            folders.insert(path.clone());
            path.parent()
        } else {
            remove_file_retrying(&path);
            path.parent()
        };
        while let Some(p) = parent {
            if p == dir {
                break;
            }
            folders.insert(p.to_path_buf());
            parent = p.parent();
        }
    }
    for folder in folders.iter().rev() {
        let _ = fs::remove_dir(folder); // only succeeds when empty
    }
    let _ = fs::remove_file(dir.join(FILE_LIST));
    Ok(())
}

pub fn uninstall(dir: &Path, remove_data: bool) -> Result<(), String> {
    system::stop_instances(&system::running_instances(dir));
    remove_installed_files(dir)?;
    // The program that started this ran from here and has just handed over to a copy in %TEMP%; give it a moment to exit.
    for _ in 0..10 {
        if fs::remove_file(dir.join(UNINSTALLER)).is_ok() || !dir.join(UNINSTALLER).exists() {
            break;
        }
        std::thread::sleep(std::time::Duration::from_millis(300));
    }
    system::remove_shortcuts("Navivi");
    system::remove_uninstall_entry();
    if remove_data {
        for d in data_dirs() {
            let _ = fs::remove_dir_all(d);
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("navivi-setup-install-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn an_empty_or_our_own_folder_is_used_as_chosen() {
        let dir = temp("own");
        assert_eq!(resolve_dir(&dir), dir);
        fs::write(dir.join(MARKER), "x").unwrap();
        fs::write(dir.join("other.txt"), "y").unwrap();
        assert_eq!(resolve_dir(&dir), dir);
    }

    #[test]
    fn a_folder_that_holds_other_things_gets_a_navivi_folder_inside() {
        let dir = temp("busy");
        fs::write(dir.join("my-documents.docx"), "y").unwrap();
        assert_eq!(resolve_dir(&dir), dir.join("Navivi"));
    }

    #[test]
    fn a_folder_already_called_navivi_is_used_even_if_not_empty() {
        let dir = temp("named").join("Navivi");
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join("old.txt"), "y").unwrap();
        assert_eq!(resolve_dir(&dir), dir);
    }

    #[test]
    fn drives_and_system_folders_are_refused_but_local_app_data_is_fine() {
        assert!(check_dir(Path::new(r"C:\")).is_err());
        assert!(check_dir(Path::new("relative/path")).is_err());
        assert!(check_dir(Path::new(r"C:\Windows\Navivi")).is_err());
        assert!(check_dir(Path::new(r"C:\Program Files\Navivi")).is_err());
        assert!(check_dir(Path::new(r"C:\Users\u\AppData\Local\Programs\Navivi")).is_ok());
        assert!(check_dir(Path::new(r"D:\Apps\Navivi")).is_ok());
    }

    #[test]
    fn uninstall_removes_only_what_was_installed_and_the_folders_it_emptied() {
        let dir = temp("remove");
        fs::create_dir_all(dir.join("src-python").join("services")).unwrap();
        fs::write(dir.join("navivi.exe"), "x").unwrap();
        fs::write(dir.join("src-python").join("services").join("a.py"), "x").unwrap();
        fs::write(dir.join("src-python").join("keep-me.log"), "user's own file").unwrap();
        fs::write(dir.join(FILE_LIST), "navivi.exe\nsrc-python/services/a.py\nsrc-python/gone.txt\n").unwrap();

        remove_installed_files(&dir).unwrap();
        assert!(!dir.join("navivi.exe").exists());
        assert!(!dir.join("src-python").join("services").exists(), "emptied folder is removed");
        assert!(dir.join("src-python").join("keep-me.log").exists(), "a file we did not install stays");
        assert!(!dir.join(FILE_LIST).exists());
    }

    #[test]
    fn a_list_entry_cannot_point_outside_the_install_folder() {
        let dir = temp("escape");
        let outside = dir.join("outside.txt");
        let inner = dir.join("app");
        fs::create_dir_all(&inner).unwrap();
        fs::write(&outside, "keep").unwrap();
        fs::write(inner.join(FILE_LIST), "../outside.txt\n").unwrap();
        remove_installed_files(&inner).unwrap();
        assert!(outside.exists());
    }
}
