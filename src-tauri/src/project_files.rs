//! Project folder housekeeping: the lean `.nvv` archive used to share a project, and the one-time tidy
//! of folders made by older versions.
//!
//! A project folder keeps the user's own work at the top (job_config.json, timeline.json, thumbnail.png,
//! raw_track.gpx, assets/) and everything generated for bookkeeping in `.navivi/`.

use serde::Serialize;
use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use walkdir::WalkDir;
use zip::write::SimpleFileOptions;
use zip::{CompressionMethod, ZipWriter};

const META_DIR: &str = ".navivi";

/// Old root file -> its place inside `.navivi/`.
const MOVED_FILES: [(&str, &str); 5] = [
    ("asset_manifest.json", "asset_manifest.json"),
    (".routecache.json", "routecache.json"),
    (".narration_cues.json", "narration_cues.json"),
    (".overview_narration.json", "overview_narration.json"),
    ("gpsdata", "gpsdata"),
];

const ALREADY_COMPRESSED: [&str; 11] = ["png", "jpg", "jpeg", "wav", "mp4", "mp3", "webm", "mov", "m4a", "mkv", "flac"];

/// Whether `rel` (a path inside the project, `/`-separated) goes into an archive made for sharing.
/// Rendered output and caches are rebuildable, so they only go in when `include_rendered` is set.
pub fn archive_includes(rel: &str, include_rendered: bool) -> bool {
    let rel = rel.trim_matches('/');
    let top = rel.split('/').next().unwrap_or("");
    if matches!(top, "cache" | ".history") {
        return false;
    }
    if !rel.contains('/') && rel.ends_with(".nvv") {
        return false; // an old copy of job_config.json, or another archive
    }
    if rel.starts_with(".navivi/gpsdata") || rel.ends_with(".tmp") || rel.ends_with(".partial") {
        return false;
    }
    if rel.starts_with("assets/video/user") {
        return true;
    }
    if rel.starts_with("assets/video") || rel.starts_with("assets/image/map") {
        return include_rendered;
    }
    true
}

/// The Mapbox token and the OpenRouteService key are app-wide now, but a project saved by an earlier version still has
/// them in `settings`. An archive made for sharing must never carry them.
const MAP_KEY_FIELDS: [&str; 2] = ["mapbox_api_key", "ors_api_key"];

/// `job_config.json`, and the old copies of it that `tidy` moved into `.navivi/legacy`.
fn may_hold_map_keys(rel: &str) -> bool {
    rel == "job_config.json" || (rel.starts_with(".navivi/legacy/") && rel.ends_with(".json"))
}

/// The file's bytes with `settings.mapbox_api_key` / `settings.ors_api_key` removed. Anything that is not a JSON
/// object, or has nothing to remove, comes back byte for byte (so a file is only rewritten when it has to be).
fn scrub_map_keys(bytes: &[u8]) -> Vec<u8> {
    let Ok(mut value) = serde_json::from_slice::<serde_json::Value>(bytes) else {
        return bytes.to_vec();
    };
    let Some(settings) = value.get_mut("settings").and_then(|s| s.as_object_mut()) else {
        return bytes.to_vec();
    };
    let mut removed = false;
    for field in MAP_KEY_FIELDS {
        removed |= settings.remove(field).is_some();
    }
    if !removed {
        return bytes.to_vec();
    }
    serde_json::to_vec_pretty(&value).unwrap_or_else(|_| bytes.to_vec())
}

pub fn write_archive(source: &Path, dest: &Path, include_rendered: bool) -> Result<u64, String> {
    let partial = PathBuf::from(format!("{}.partial", dest.display()));
    let result = write_archive_to(source, &partial, include_rendered);
    match result {
        Ok(()) => {
            if dest.exists() {
                fs::remove_file(dest).map_err(|e| e.to_string())?;
            }
            fs::rename(&partial, dest).map_err(|e| e.to_string())?;
            fs::metadata(dest).map(|m| m.len()).map_err(|e| e.to_string())
        }
        Err(e) => {
            let _ = fs::remove_file(&partial);
            Err(e)
        }
    }
}

fn write_archive_to(source: &Path, partial: &Path, include_rendered: bool) -> Result<(), String> {
    let file = fs::File::create(partial).map_err(|e| e.to_string())?;
    let mut zip = ZipWriter::new(file);
    for entry in WalkDir::new(source).into_iter().filter_map(|e| e.ok()) {
        if !entry.file_type().is_file() {
            continue;
        }
        let rel = entry
            .path()
            .strip_prefix(source)
            .map_err(|e| e.to_string())?
            .to_string_lossy()
            .replace('\\', "/");
        if !archive_includes(&rel, include_rendered) {
            continue;
        }
        let ext = Path::new(&rel).extension().and_then(|e| e.to_str()).unwrap_or("").to_lowercase();
        let method = if ALREADY_COMPRESSED.contains(&ext.as_str()) { CompressionMethod::Stored } else { CompressionMethod::Deflated };
        zip.start_file(&rel, SimpleFileOptions::default().compression_method(method)).map_err(|e| e.to_string())?;
        if may_hold_map_keys(&rel) {
            let bytes = fs::read(entry.path()).map_err(|e| e.to_string())?;
            zip.write_all(&scrub_map_keys(&bytes)).map_err(|e| e.to_string())?;
        } else {
            let mut input = fs::File::open(entry.path()).map_err(|e| e.to_string())?;
            io::copy(&mut input, &mut zip).map_err(|e| e.to_string())?;
        }
    }
    zip.finish().map_err(|e| e.to_string())?;
    Ok(())
}

#[derive(Serialize, Default, Debug)]
pub struct TidyReport {
    pub moved: Vec<String>,
    pub removed: Vec<String>,
    pub kept: Vec<String>,
}

fn is_zip(path: &Path) -> bool {
    fs::File::open(path)
        .and_then(|mut f| {
            let mut head = [0u8; 2];
            io::Read::read_exact(&mut f, &mut head).map(|_| head == *b"PK")
        })
        .unwrap_or(false)
}

/// One-time cleanup of a folder made by an older version. Safe to run again: it only moves or removes
/// what it finds, and anything it can't place without overwriting is left where it is and reported.
pub fn tidy(project: &Path, shared_tile_cache: &Path, remove_history: bool) -> Result<TidyReport, String> {
    let config = project.join("job_config.json");
    let copies: Vec<PathBuf> = fs::read_dir(project)
        .map_err(|e| e.to_string())?
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| p.is_file() && p.extension().is_some_and(|e| e == "nvv") && !is_zip(p))
        .collect();
    if !config.exists() && copies.is_empty() {
        return Err(format!("{} does not look like a project folder", project.display()));
    }

    let mut report = TidyReport::default();
    let meta = project.join(META_DIR);
    let name_of = |p: &Path| p.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();

    // `<name>.nvv` inside the folder used to be a second copy of job_config.json.
    for copy in copies {
        if !config.exists() {
            fs::rename(&copy, &config).map_err(|e| e.to_string())?;
            report.moved.push(format!("{} -> job_config.json", name_of(&copy)));
        } else if fs::read(&copy).map_err(|e| e.to_string())? == fs::read(&config).map_err(|e| e.to_string())? {
            fs::remove_file(&copy).map_err(|e| e.to_string())?;
            report.removed.push(name_of(&copy));
        } else {
            // Different from job_config.json: keep it, out of the way.
            let legacy = meta.join("legacy");
            fs::create_dir_all(&legacy).map_err(|e| e.to_string())?;
            fs::rename(&copy, legacy.join(format!("{}.json", name_of(&copy)))).map_err(|e| e.to_string())?;
            report.kept.push(format!("{} (differs from job_config.json) -> .navivi/legacy", name_of(&copy)));
        }
    }

    for (old, new) in MOVED_FILES {
        let from = project.join(old);
        if !from.exists() {
            continue;
        }
        let to = meta.join(new);
        if to.exists() {
            report.kept.push(format!("{} (.navivi/{} already exists)", old, new));
            continue;
        }
        fs::create_dir_all(&meta).map_err(|e| e.to_string())?;
        fs::rename(&from, &to).map_err(|e| e.to_string())?;
        report.moved.push(format!("{} -> .navivi/{}", old, new));
    }

    // Map tiles are shared by every project now.
    let cache = project.join("cache");
    if cache.is_dir() {
        if shared_tile_cache.exists() {
            fs::remove_dir_all(&cache).map_err(|e| e.to_string())?;
            report.removed.push("cache (tiles are shared now)".to_string());
        } else {
            if let Some(parent) = shared_tile_cache.parent() {
                fs::create_dir_all(parent).map_err(|e| e.to_string())?;
            }
            match fs::rename(&cache, shared_tile_cache) {
                Ok(()) => report.moved.push("cache -> shared tile cache".to_string()),
                Err(e) => report.kept.push(format!("cache (could not move: {e})")),
            }
        }
    }

    if remove_history && project.join(".history").is_dir() {
        fs::remove_dir_all(project.join(".history")).map_err(|e| e.to_string())?;
        report.removed.push(".history (versions live in the app database)".to_string());
    }
    Ok(report)
}

#[tauri::command]
pub async fn export_project_archive(source_dir: String, dest_file: String, include_rendered: bool) -> Result<u64, String> {
    tauri::async_runtime::spawn_blocking(move || write_archive(Path::new(&source_dir), Path::new(&dest_file), include_rendered))
        .await
        .map_err(|e| e.to_string())?
}

/// Copies a project folder for "Duplicate". Leaves out what is not the user's work (`.history`, the old tile `cache`,
/// archives in the root); the caller rewrites job_config.json for the copy.
pub fn copy_project(source: &Path, dest: &Path) -> Result<(), String> {
    if !source.is_dir() {
        return Err(format!("{} is not a project folder", source.display()));
    }
    if dest.exists() {
        return Err(format!("{} already exists", dest.display()));
    }
    fs::create_dir_all(dest).map_err(|e| e.to_string())?;
    for entry in WalkDir::new(source).min_depth(1) {
        let entry = entry.map_err(|e| e.to_string())?;
        let rel = entry.path().strip_prefix(source).map_err(|e| e.to_string())?;
        let top = rel.components().next().and_then(|c| c.as_os_str().to_str()).unwrap_or("");
        let in_root = rel.components().count() == 1;
        let is_archive = in_root && entry.file_type().is_file() && matches!(rel.extension().and_then(|e| e.to_str()), Some("nvv") | Some("zip"));
        if top == ".history" || top == "cache" || is_archive {
            continue;
        }
        let target = dest.join(rel);
        if entry.file_type().is_dir() {
            fs::create_dir_all(&target).map_err(|e| e.to_string())?;
        } else {
            fs::copy(entry.path(), &target).map_err(|e| format!("{}: {}", rel.display(), e))?;
        }
    }
    Ok(())
}

#[tauri::command]
pub async fn duplicate_project_folder(source_dir: String, dest_dir: String) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || copy_project(Path::new(&source_dir), Path::new(&dest_dir)))
        .await
        .map_err(|e| e.to_string())?
}

#[tauri::command]
pub async fn tidy_project_folder(project_dir: String, shared_tile_cache: String, remove_history: bool) -> Result<TidyReport, String> {
    tauri::async_runtime::spawn_blocking(move || tidy(Path::new(&project_dir), Path::new(&shared_tile_cache), remove_history))
        .await
        .map_err(|e| e.to_string())?
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    static COUNTER: AtomicUsize = AtomicUsize::new(0);

    fn scratch() -> PathBuf {
        let dir = std::env::temp_dir().join(format!("navivi_test_{}_{}", std::process::id(), COUNTER.fetch_add(1, Ordering::SeqCst)));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn write(path: &Path, text: &str) {
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, text).unwrap();
    }

    #[test]
    fn duplicate_copies_the_work_and_not_the_clutter() {
        let src = scratch();
        let dest = scratch().join("copy");
        write(&src.join("job_config.json"), "{}");
        write(&src.join("assets/image/a.jpg"), "img");
        write(&src.join("assets/audio/a.wav"), "wav");
        write(&src.join(".navivi/routecache.json"), "{}");
        write(&src.join(".history/v1.json"), "{}");
        write(&src.join("cache/tiles/t.png"), "tile");
        write(&src.join("old.nvv"), "{}");
        write(&src.join("assets/video/user/mine.mp4"), "vid");
        copy_project(&src, &dest).unwrap();
        for kept in ["job_config.json", "assets/image/a.jpg", "assets/audio/a.wav", ".navivi/routecache.json", "assets/video/user/mine.mp4"] {
            assert!(dest.join(kept).is_file(), "{kept} should be copied");
        }
        for left in [".history", "cache", "old.nvv"] {
            assert!(!dest.join(left).exists(), "{left} should not be copied");
        }
        assert!(copy_project(&src, &dest).is_err(), "must not copy over an existing folder");
    }

    #[test]
    fn lean_archive_skips_rebuildable_files() {
        assert!(archive_includes("job_config.json", false));
        assert!(archive_includes("assets/audio/a.wav", false));
        assert!(archive_includes("assets/image/photo.jpg", false));
        assert!(archive_includes("assets/video/user/mine.mp4", false));
        assert!(!archive_includes("assets/video/route/01.mp4", false));
        assert!(!archive_includes("assets/image/map/res_map.png", false));
        assert!(!archive_includes("cache/contextily/x.pkl", true));
        assert!(!archive_includes(".history/a.json", true));
        assert!(!archive_includes("shirahama.nvv", true));
        assert!(!archive_includes(".navivi/gpsdata/gpsdata.csv", true));
        assert!(archive_includes(".navivi/routecache.json", false));
        assert!(archive_includes("assets/video/route/01.mp4", true));
    }

    #[test]
    fn archive_round_trips_through_zip() {
        let src = scratch();
        write(&src.join("job_config.json"), "{}");
        write(&src.join("assets/audio/a.wav"), "wav");
        write(&src.join("assets/video/route/r.mp4"), "video");
        write(&src.join("cache/c.pkl"), "tiles");
        let out = scratch().join("p.nvv");

        write_archive(&src, &out, false).unwrap();
        let mut zip = zip::ZipArchive::new(fs::File::open(&out).unwrap()).unwrap();
        let names: Vec<String> = (0..zip.len()).map(|i| zip.by_index(i).unwrap().name().to_string()).collect();
        assert!(names.contains(&"job_config.json".to_string()));
        assert!(names.contains(&"assets/audio/a.wav".to_string()));
        assert!(!names.iter().any(|n| n.contains("route") || n.contains("cache")));
        assert!(!out.with_extension("nvv.partial").exists());
    }

    fn read_entry(archive: &Path, name: &str) -> String {
        let mut zip = zip::ZipArchive::new(fs::File::open(archive).unwrap()).unwrap();
        let mut text = String::new();
        io::Read::read_to_string(&mut zip.by_name(name).unwrap(), &mut text).unwrap();
        text
    }

    #[test]
    fn a_shared_archive_never_carries_the_map_keys() {
        let src = scratch();
        let config = r#"{"project_id":"p","project_name":"京都","settings":{"fps":30,"mapbox_api_key":"pk.secret","ors_api_key":"ors-secret","line_color":"#fff"},"waypoints":[]}"#;
        write(&src.join("job_config.json"), config);
        write(&src.join(".navivi/legacy/Old.nvv.json"), r#"{"settings":{"mapbox_api_key":"pk.old"}}"#);
        write(&src.join(".navivi/routecache.json"), r#"{"settings":{"mapbox_api_key":"not-a-config"}}"#);
        let out = scratch().join("p.nvv");

        write_archive(&src, &out, false).unwrap();

        let shared: serde_json::Value = serde_json::from_str(&read_entry(&out, "job_config.json")).unwrap();
        assert_eq!(shared["settings"]["fps"], 30);
        assert_eq!(shared["settings"]["line_color"], "#fff");
        assert_eq!(shared["project_name"], "京都");
        assert!(shared["settings"].get("mapbox_api_key").is_none());
        assert!(shared["settings"].get("ors_api_key").is_none());
        assert!(!read_entry(&out, ".navivi/legacy/Old.nvv.json").contains("pk.old"));
        // Only the project file and its old copies are rewritten.
        assert!(read_entry(&out, ".navivi/routecache.json").contains("not-a-config"));
        // The project on disk is left as it was.
        assert_eq!(fs::read_to_string(src.join("job_config.json")).unwrap(), config);
    }

    #[test]
    fn scrubbing_leaves_a_clean_or_unreadable_file_byte_for_byte() {
        let clean = br#"{"settings":{"fps":30}}"#;
        assert_eq!(scrub_map_keys(clean), clean.to_vec());
        let no_settings = br#"{"a":1}"#;
        assert_eq!(scrub_map_keys(no_settings), no_settings.to_vec());
        let broken = b"{not json";
        assert_eq!(scrub_map_keys(broken), broken.to_vec());
    }

    #[test]
    fn tidy_removes_the_duplicate_and_moves_generated_files() {
        let dir = scratch();
        write(&dir.join("job_config.json"), "{\"a\":1}");
        write(&dir.join("Trip.nvv"), "{\"a\":1}");
        write(&dir.join(".routecache.json"), "{}");
        write(&dir.join("asset_manifest.json"), "{}");
        write(&dir.join("gpsdata/gpsdata.csv"), "x");
        write(&dir.join(".history/manifest.json"), "{}");
        write(&dir.join("cache/contextily/t.pkl"), "tiles");
        let shared = scratch().join("Cache").join("tiles");

        let report = tidy(&dir, &shared, true).unwrap();
        assert!(!dir.join("Trip.nvv").exists());
        assert!(dir.join("job_config.json").exists());
        assert!(dir.join(".navivi/routecache.json").exists());
        assert!(dir.join(".navivi/asset_manifest.json").exists());
        assert!(dir.join(".navivi/gpsdata/gpsdata.csv").exists());
        assert!(!dir.join(".history").exists());
        assert!(shared.join("contextily/t.pkl").exists());
        assert!(!dir.join("cache").exists());
        assert!(report.kept.is_empty());

        // Running it again changes nothing and fails nothing.
        let again = tidy(&dir, &shared, true).unwrap();
        assert!(again.moved.is_empty() && again.removed.is_empty());
    }

    #[test]
    fn tidy_keeps_a_differing_copy_and_promotes_a_lone_one() {
        let dir = scratch();
        write(&dir.join("job_config.json"), "{\"a\":2}");
        write(&dir.join("Trip.nvv"), "{\"a\":1}");
        let shared = scratch().join("tiles");
        let report = tidy(&dir, &shared, false).unwrap();
        assert_eq!(report.kept.len(), 1);
        assert!(dir.join(".navivi/legacy/Trip.nvv.json").exists());

        let lone = scratch();
        write(&lone.join("Old.nvv"), "{\"a\":3}");
        tidy(&lone, &shared, false).unwrap();
        assert_eq!(fs::read_to_string(lone.join("job_config.json")).unwrap(), "{\"a\":3}");
    }

    #[test]
    fn a_shared_cache_that_exists_wins_and_a_zip_named_nvv_is_left_alone() {
        let dir = scratch();
        write(&dir.join("job_config.json"), "{}");
        write(&dir.join("cache/t.pkl"), "tiles");
        let shared = scratch();
        fs::write(dir.join("share.nvv"), b"PK\x03\x04rest").unwrap();
        let report = tidy(&dir, &shared, false).unwrap();
        assert!(!dir.join("cache").exists());
        assert!(dir.join("share.nvv").exists());
        assert!(report.removed.iter().any(|r| r.starts_with("cache")));
    }

    #[test]
    fn a_random_folder_is_refused() {
        assert!(tidy(&scratch(), &scratch(), true).is_err());
    }
}
