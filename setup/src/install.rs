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
    /// Something worth telling the user that did not stop the install.
    Note { name: &'static str },
}

pub fn default_dir() -> PathBuf {
    // A remembered location is trusted no further than a freshly chosen one: the registry value can be stale or edited.
    system::previous_install_dir()
        .filter(|d| check_dir(d).is_ok())
        .unwrap_or_else(|| system::local_app_data().join("Programs").join("Navivi"))
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

/// Why a folder cannot be the install folder. `code` is what the window translates; `english` is for the log and the error screen.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum DirProblem {
    Drive,
    System,
    Network,
    /// The folder is, holds, or sits inside the user's own Navivi data (projects, engines, the database).
    UserData,
}

impl DirProblem {
    pub fn code(self) -> &'static str {
        match self {
            DirProblem::Drive => "drive",
            DirProblem::System => "system",
            DirProblem::Network => "network",
            DirProblem::UserData => "userdata",
        }
    }

    pub fn english(self) -> &'static str {
        match self {
            DirProblem::Drive => "Choose a folder, not a whole drive.",
            DirProblem::System => "Choose a folder you can write to, such as the default one.",
            DirProblem::Network => "Choose a folder on this PC, not a network location.",
            DirProblem::UserData => "That folder is where Navivi keeps your projects and data. Choose another folder, such as the default one.",
        }
    }
}

/// A path as comparable text: backslashes, no trailing separator, lower case (Windows paths ignore case).
fn comparable(path: &Path) -> String {
    path.display().to_string().replace('/', "\\").trim_end_matches('\\').to_lowercase()
}

fn is_inside(child: &str, parent: &str) -> bool {
    child == parent || child.starts_with(&format!("{parent}\\"))
}

/// The folders an install must never be, hold or sit inside: where the user's projects, engines and database live.
pub fn protected_dirs() -> Vec<PathBuf> {
    let roots = DataRoots::real();
    vec![roots.documents, roots.local, roots.roaming]
}

/// Refuses folders no install belongs in: a drive root, a Windows system folder, a network path, or the user's own data.
pub fn check_dir(dir: &Path) -> Result<(), DirProblem> {
    check_dir_with(dir, &protected_dirs())
}

pub fn check_dir_with(dir: &Path, protected: &[PathBuf]) -> Result<(), DirProblem> {
    if !dir.is_absolute() || dir.parent().is_none() {
        return Err(DirProblem::Drive);
    }
    let text = dir.display().to_string();
    // \\server\share and \\?\... (which can also name a local drive in a form no check here understands).
    if text.starts_with(r"\\") || text.starts_with("//") {
        return Err(DirProblem::Network);
    }
    // The first folder under the drive, compared as a whole name: "D:\windows-tools" is fine, "C:\Windows" is not.
    let first = dir.components().find_map(|c| match c {
        std::path::Component::Normal(name) => Some(name.to_string_lossy().to_lowercase()),
        _ => None,
    });
    if let Some(first) = first {
        if ["windows", "program files", "program files (x86)", "programdata"].contains(&first.as_str()) {
            return Err(DirProblem::System);
        }
    }
    let here = comparable(dir);
    for p in protected {
        let theirs = comparable(p);
        if !theirs.is_empty() && (is_inside(&here, &theirs) || is_inside(&theirs, &here)) {
            return Err(DirProblem::UserData);
        }
    }
    Ok(())
}

pub fn install(opts: &Options, payload: &Payload, mut emit: impl FnMut(Event)) -> Result<Manifest, String> {
    check_dir(&opts.dir).map_err(|p| p.english().to_string())?;
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
    // The list goes down before the first file does: old plus new, so a copy that stops half way (a locked file, a full disk)
    // leaves an install the uninstaller can still remove completely.
    let old_list = fs::read_to_string(opts.dir.join(FILE_LIST)).unwrap_or_default();
    let planned = payload::planned_names(&mut archive)?;
    fs::write(opts.dir.join(FILE_LIST), merged_list(&old_list, &planned)).map_err(|e| format!("{}: {e}", opts.dir.display()))?;
    let mut last_pct = -1.0;
    let written = payload::extract(&mut archive, &opts.dir, |done, total, file| {
        let pct = if total == 0 { 100.0 } else { (done as f64 / total as f64 * 1000.0).round() / 10.0 };
        if pct != last_pct {
            last_pct = pct;
            emit(Event::Progress { pct, file: file.to_string() });
        }
    })?;

    emit(Event::Step { name: "finishing" });
    remove_stale(&opts.dir, &old_list, &written);
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

    // Last, so that a refused permission prompt or no internet never costs the install itself: only the voices need this.
    if !system::vc_runtime_installed() {
        emit(Event::Step { name: "runtime" });
        if system::install_vc_runtime().is_err() {
            emit(Event::Note { name: "runtimeMissing" });
        }
    }
    Ok(manifest)
}

/// What `.navivi-files.txt` holds while a copy is under way: everything the previous version installed plus everything this one will.
pub fn merged_list(old: &str, planned: &[String]) -> String {
    let mut seen = std::collections::HashSet::new();
    let mut out = String::new();
    for line in old.lines().map(str::trim).filter(|l| !l.is_empty()).chain(planned.iter().map(String::as_str)) {
        if seen.insert(line.to_string()) {
            out.push_str(line);
            out.push('\n');
        }
    }
    out
}

/// After an update: deletes what the previous version installed and this one no longer has, so old files do not pile up and the
/// new list (which only names what is there now) still covers everything. Only files the installer itself listed are touched,
/// and a folder only goes if it is empty by then.
pub fn remove_stale(dir: &Path, old: &str, written: &[String]) {
    let keep: std::collections::HashSet<&str> = written.iter().map(String::as_str).collect();
    let mut folders = std::collections::BTreeSet::new();
    for rel in old.lines().map(str::trim).filter(|l| !l.is_empty() && !keep.contains(l)) {
        if rel == FILE_LIST || rel == UNINSTALLER {
            continue;
        }
        let Some(path) = payload::safe_join(dir, rel) else { continue };
        if rel.ends_with('/') {
            folders.insert(path);
        } else {
            remove_file_retrying(&path);
            let mut parent = path.parent();
            while let Some(p) = parent {
                if p == dir {
                    break;
                }
                folders.insert(p.to_path_buf());
                parent = p.parent();
            }
        }
    }
    for folder in folders.iter().rev() {
        let _ = fs::remove_dir(folder);
    }
}

/// The uninstaller is this exe without the payload.
fn write_uninstaller(setup_exe: &Path, plain_len: u64, to: &Path) -> Result<(), String> {
    use std::io::Read;
    let mut bytes = Vec::with_capacity(plain_len as usize);
    fs::File::open(setup_exe).map_err(|e| e.to_string())?.take(plain_len).read_to_end(&mut bytes).map_err(|e| e.to_string())?;
    // A signed setup's signature lies beyond what is copied; clear its entry so the copy is a plain unsigned exe.
    if let Some((at, offset, _)) = crate::payload::security_entry(&bytes) {
        if offset > 0 {
            bytes[at..at + 8].fill(0);
        }
    }
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

/// The kinds of data the app keeps outside its install folder, which the user can keep or remove one by one. The projects in
/// Documents\Navivi\Workspaces are never in this list: the uninstaller does not touch them.
pub const DATA_IDS: [&str; 6] = ["runtime", "engines", "voices", "cache", "settings", "keys"];

/// The three folders the app's data lives under, passed in so tests can point them at a temp folder instead of the real ones.
pub struct DataRoots {
    /// `%LOCALAPPDATA%\navivi`: the Python environment, the engines, downloads and the webview's own data.
    pub local: PathBuf,
    /// `%APPDATA%\navivi`: the database.
    pub roaming: PathBuf,
    /// `Documents\Navivi`: the shared map cache (and the projects, which are never touched).
    pub documents: PathBuf,
}

impl DataRoots {
    pub fn real() -> Self {
        DataRoots {
            local: system::local_app_data().join("navivi"),
            roaming: system::roaming_app_data().join("navivi"),
            documents: system::documents_dir().join("Navivi"),
        }
    }

    /// Where the natural voice's engine keeps the user's recorded voices (src-python/services/tts/voices.py `voices_dir`). It sits
    /// inside the engine folder, so removing the engines has to step around it.
    fn voices(&self) -> PathBuf {
        self.local.join("bin").join("Irodori-TTS-Server").join("voices")
    }

    /// Size of one kind of data in bytes (0 for saved keys, which are not files).
    pub fn size_of(&self, id: &str) -> u64 {
        match id {
            "runtime" => dir_size(&self.local.join("runtime")),
            "engines" => dir_size(&self.local.join("bin")).saturating_sub(dir_size(&self.voices())) + dir_size(&self.local.join("downloads")),
            "voices" => dir_size(&self.voices()),
            "cache" => dir_size(&self.documents.join("Cache")),
            "settings" => dir_size(&self.roaming) + dir_size(&self.local.join("EBWebView")),
            _ => 0,
        }
    }

    /// Removes the chosen kinds of data. Unknown ids are ignored, so nothing but what is listed here can ever be deleted, and
    /// the voices survive "engines" because that step walks around them.
    pub fn remove(&self, ids: &[String], delete_keys: impl Fn()) {
        for id in ids {
            match id.as_str() {
                "runtime" => remove_tree(&self.local.join("runtime")),
                "engines" => {
                    remove_all_except(&self.local.join("bin"), &self.voices());
                    remove_tree(&self.local.join("downloads"));
                }
                "voices" => remove_tree(&self.voices()),
                "cache" => remove_tree(&self.documents.join("Cache")),
                "settings" => {
                    remove_tree(&self.roaming);
                    remove_tree(&self.local.join("EBWebView"));
                }
                "keys" => delete_keys(),
                _ => {}
            }
        }
        // Folders that are now empty go too; remove_dir leaves any that still hold something the user chose to keep.
        for dir in [self.voices(), self.local.join("bin").join("Irodori-TTS-Server"), self.local.join("bin"), self.local.clone()] {
            let _ = fs::remove_dir(dir);
        }
    }
}

pub fn data_size_of(id: &str) -> u64 {
    DataRoots::real().size_of(id)
}

fn remove_tree(path: &Path) {
    let _ = if path.is_dir() { fs::remove_dir_all(path) } else { fs::remove_file(path) };
}

/// Deletes everything inside `dir` except `keep` and the folders leading to it.
fn remove_all_except(dir: &Path, keep: &Path) {
    let Ok(entries) = fs::read_dir(dir) else { return };
    for entry in entries.flatten() {
        let path = entry.path();
        if path == keep {
            continue;
        }
        if keep.starts_with(&path) {
            remove_all_except(&path, keep);
        } else {
            remove_tree(&path);
        }
    }
}

pub fn remove_data(ids: &[String]) {
    if !ids.is_empty() {
        DataRoots::real().remove(ids, system::delete_saved_keys);
    }
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

pub fn uninstall(dir: &Path, remove: &[String]) -> Result<(), String> {
    system::stop_instances(&system::running_instances(dir));
    remove_installed_files(dir)?;
    // The program that started this ran from here and has just handed over to a copy in %TEMP%; give it a moment to exit.
    for _ in 0..10 {
        if fs::remove_file(dir.join(UNINSTALLER)).is_ok() || !dir.join(UNINSTALLER).exists() {
            break;
        }
        std::thread::sleep(std::time::Duration::from_millis(300));
    }
    system::remove_shortcuts("Navivi", dir);
    system::remove_uninstall_entry(dir);
    remove_data(remove);
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
        let none: &[PathBuf] = &[];
        assert_eq!(check_dir_with(Path::new(r"C:\"), none), Err(DirProblem::Drive));
        assert_eq!(check_dir_with(Path::new("relative/path"), none), Err(DirProblem::Drive));
        assert_eq!(check_dir_with(Path::new(r"C:\Windows\Navivi"), none), Err(DirProblem::System));
        assert_eq!(check_dir_with(Path::new(r"C:\Program Files\Navivi"), none), Err(DirProblem::System));
        assert_eq!(check_dir_with(Path::new(r"C:\ProgramData\Navivi"), none), Err(DirProblem::System));
        assert!(check_dir_with(Path::new(r"C:\Users\u\AppData\Local\Programs\Navivi"), none).is_ok());
        assert!(check_dir_with(Path::new(r"D:\Apps\Navivi"), none).is_ok());
    }

    #[test]
    fn a_folder_that_only_starts_like_a_system_folder_is_fine() {
        let none: &[PathBuf] = &[];
        assert!(check_dir_with(Path::new(r"D:\windows-tools\Navivi"), none).is_ok());
        assert!(check_dir_with(Path::new(r"D:\Program Files Portable\Navivi"), none).is_ok());
    }

    #[test]
    fn network_and_verbatim_paths_are_refused() {
        let none: &[PathBuf] = &[];
        assert_eq!(check_dir_with(Path::new(r"\\server\share\Navivi"), none), Err(DirProblem::Network));
        assert_eq!(check_dir_with(Path::new(r"\\?\C:\Users\u\Navivi"), none), Err(DirProblem::Network));
    }

    #[test]
    fn the_users_own_navivi_data_is_never_an_install_folder() {
        let protected = vec![
            PathBuf::from(r"C:\Users\u\Documents\Navivi"),
            PathBuf::from(r"C:\Users\u\AppData\Local\navivi"),
            PathBuf::from(r"C:\Users\u\AppData\Roaming\navivi"),
        ];
        for bad in [
            r"C:\Users\u\Documents\Navivi",
            r"c:\users\u\documents\navivi\",
            r"C:\Users\u\Documents\Navivi\Workspaces",
            r"C:\Users\u\AppData\Local\navivi",
            r"C:\Users\u\AppData\Local\navivi\bin",
            r"C:\Users\u\AppData\Roaming\Navivi",
        ] {
            assert_eq!(check_dir_with(Path::new(bad), &protected), Err(DirProblem::UserData), "{bad}");
        }
        // Their neighbors are fine, including the default install folder.
        for good in [
            r"C:\Users\u\AppData\Local\Programs\Navivi",
            r"C:\Users\u\Documents\Navivi-app",
            r"C:\Users\u\Documents\Apps\Navivi",
            r"D:\Apps\Navivi",
        ] {
            assert!(check_dir_with(Path::new(good), &protected).is_ok(), "{good}");
        }
    }

    #[test]
    fn choosing_documents_resolves_into_the_protected_folder_and_is_refused() {
        // Documents holds other things, so the chosen folder becomes Documents\Navivi, which is the user's data.
        let docs = temp("docs-choice");
        fs::write(docs.join("letter.docx"), "x").unwrap();
        let resolved = resolve_dir(&docs);
        assert_eq!(resolved, docs.join("Navivi"));
        assert_eq!(check_dir_with(&resolved, &[docs.join("Navivi")]), Err(DirProblem::UserData));
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

    fn roots(name: &str) -> DataRoots {
        let base = temp(name);
        let roots = DataRoots { local: base.join("local"), roaming: base.join("roaming"), documents: base.join("docs") };
        for (path, text) in [
            (roots.local.join("runtime").join("python.exe"), "py"),
            (roots.local.join("bin").join("Kokoro-TTS").join("model.pth"), "model"),
            (roots.local.join("bin").join("Irodori-TTS-Server").join("server.py"), "server"),
            (roots.voices().join("mine.wav"), "my recorded voice"),
            (roots.local.join("downloads").join("x.zip"), "zip"),
            (roots.local.join("EBWebView").join("cache"), "web"),
            (roots.roaming.join("navivi.db"), "db"),
            (roots.documents.join("Cache").join("tile.png"), "tile"),
            (roots.documents.join("Workspaces").join("trip").join("job_config.json"), "{}"),
        ] {
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(path, text).unwrap();
        }
        roots
    }

    fn remove(roots: &DataRoots, ids: &[&str]) -> usize {
        let keys_deleted = std::cell::Cell::new(0);
        let ids: Vec<String> = ids.iter().map(|s| s.to_string()).collect();
        roots.remove(&ids, || keys_deleted.set(keys_deleted.get() + 1));
        keys_deleted.get()
    }

    #[test]
    fn removing_the_engines_keeps_the_recorded_voices() {
        let r = roots("engines");
        remove(&r, &["engines"]);
        assert!(!r.local.join("bin").join("Kokoro-TTS").exists());
        assert!(!r.local.join("bin").join("Irodori-TTS-Server").join("server.py").exists());
        assert!(!r.local.join("downloads").exists());
        assert!(r.voices().join("mine.wav").exists(), "a recorded voice cannot be recreated");
        assert!(r.local.join("runtime").join("python.exe").exists(), "only what was chosen goes");
    }

    #[test]
    fn each_kind_of_data_goes_on_its_own() {
        for (id, gone, stays) in [
            ("runtime", "local/runtime", "docs/Cache"),
            ("voices", "local/bin/Irodori-TTS-Server/voices", "local/bin/Kokoro-TTS"),
            ("cache", "docs/Cache", "roaming/navivi.db"),
            ("settings", "roaming/navivi.db", "local/runtime"),
        ] {
            let r = roots(&format!("one-{id}"));
            let base = r.local.parent().unwrap().to_path_buf();
            remove(&r, &[id]);
            assert!(!base.join(gone).exists(), "{id} should remove {gone}");
            assert!(base.join(stays).exists(), "{id} should keep {stays}");
        }
    }

    #[test]
    fn projects_and_unknown_ids_are_never_touched() {
        let r = roots("projects");
        let project = r.documents.join("Workspaces").join("trip").join("job_config.json");
        remove(&r, &["runtime", "engines", "voices", "cache", "settings", "keys", "Workspaces", "..", "everything"]);
        assert!(project.exists(), "the projects stay whatever is chosen");
        let r = roots("unknown");
        remove(&r, &["Workspaces", "..", "bin", ""]);
        assert!(r.local.join("bin").join("Kokoro-TTS").join("model.pth").exists());
        assert!(r.documents.join("Workspaces").exists());
    }

    #[test]
    fn saved_keys_are_deleted_only_when_chosen() {
        let r = roots("keys");
        assert_eq!(remove(&r, &["runtime"]), 0);
        assert_eq!(remove(&r, &["keys"]), 1);
    }

    #[test]
    fn sizes_are_counted_per_kind_and_voices_are_not_part_of_the_engines() {
        let r = roots("sizes");
        assert_eq!(r.size_of("voices"), "my recorded voice".len() as u64);
        assert_eq!(r.size_of("engines"), ("model".len() + "server".len() + "zip".len()) as u64);
        assert_eq!(r.size_of("keys"), 0);
    }

    #[test]
    fn the_list_saved_before_copying_covers_the_old_files_and_the_new_ones() {
        let merged = merged_list("navivi.exe\nold/gone.py\n", &["navivi.exe".to_string(), "new/added.py".to_string()]);
        assert_eq!(merged, "navivi.exe\nold/gone.py\nnew/added.py\n");
        assert_eq!(merged_list("", &["a".to_string()]), "a\n");
    }

    #[test]
    fn an_update_removes_what_the_old_version_had_and_the_new_one_does_not() {
        let dir = temp("stale");
        for (path, text) in [("navivi.exe", "new"), ("src-python/kept.py", "k"), ("src-python/old/removed.py", "r"), ("notes.txt", "the user's own file")] {
            let full = dir.join(path);
            fs::create_dir_all(full.parent().unwrap()).unwrap();
            fs::write(full, text).unwrap();
        }
        let old = "navivi.exe\nsrc-python/kept.py\nsrc-python/old/removed.py\nsrc-python/old/\n../outside.txt\n";
        let written = vec!["navivi.exe".to_string(), "src-python/kept.py".to_string()];
        remove_stale(&dir, old, &written);
        assert!(dir.join("navivi.exe").exists() && dir.join("src-python/kept.py").exists());
        assert!(!dir.join("src-python/old").exists(), "the file the new version dropped and its empty folder are gone");
        assert!(dir.join("notes.txt").exists(), "a file the installer never listed stays");
    }

    #[test]
    fn an_update_never_deletes_a_folder_that_still_holds_something() {
        let dir = temp("stale-busy");
        fs::create_dir_all(dir.join("src-python/old")).unwrap();
        fs::write(dir.join("src-python/old/removed.py"), "r").unwrap();
        fs::write(dir.join("src-python/old/user-made.log"), "mine").unwrap();
        remove_stale(&dir, "src-python/old/removed.py\n", &[]);
        assert!(!dir.join("src-python/old/removed.py").exists());
        assert!(dir.join("src-python/old/user-made.log").exists());
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
