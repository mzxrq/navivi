use rusqlite::Connection;

use super::error::{DbError, DbResult};

// Append-only: never edit a shipped entry, add a new one. Index + 1 = user_version.
const MIGRATIONS: &[&str] = &[r#"
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    name TEXT NOT NULL,
    theme TEXT,
    status TEXT NOT NULL DEFAULT 'saved',
    directory_path TEXT NOT NULL UNIQUE,
    archive_path TEXT,
    thumbnail_path TEXT,
    video_title TEXT NOT NULL DEFAULT '',
    video_subtitle TEXT NOT NULL DEFAULT '',
    enable_intro INTEGER NOT NULL DEFAULT 1,
    overview_narration TEXT NOT NULL DEFAULT '',
    overview_narration_is_auto INTEGER NOT NULL DEFAULT 0,
    overview_narration_source_ids TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(overview_narration_source_ids)),
    created_at TEXT NOT NULL,
    updated_at INTEGER NOT NULL,
    last_opened_at INTEGER,
    deleted_at INTEGER
);
CREATE INDEX idx_projects_recent ON projects(last_opened_at DESC) WHERE deleted_at IS NULL;

CREATE TABLE project_settings (
    project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    settings_json TEXT NOT NULL CHECK (json_valid(settings_json)),
    updated_at INTEGER NOT NULL
);

CREATE TABLE project_versions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    project_name TEXT NOT NULL,
    label TEXT NOT NULL,
    created_at TEXT NOT NULL,
    waypoint_count INTEGER NOT NULL,
    clip_count INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL CHECK (json_valid(snapshot_json))
);
CREATE INDEX idx_versions_project ON project_versions(project_id, created_at DESC);

CREATE TABLE route_cache (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    cache_key TEXT NOT NULL,
    points_json TEXT NOT NULL CHECK (json_valid(points_json)),
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (project_id, cache_key)
);

CREATE TABLE app_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL CHECK (json_valid(value_json)),
    updated_at INTEGER NOT NULL
);
"#];

pub fn migrate(conn: &mut Connection) -> DbResult<()> {
    let current: usize = conn.query_row("PRAGMA user_version", [], |r| r.get::<_, i64>(0))? as usize;
    if current > MIGRATIONS.len() {
        return Err(DbError::Invalid(format!(
            "database schema v{current} is newer than this app (v{})",
            MIGRATIONS.len()
        )));
    }
    let tx = conn.transaction()?;
    for (i, sql) in MIGRATIONS.iter().enumerate().skip(current) {
        tx.execute_batch(sql)?;
        tx.pragma_update(None, "user_version", (i + 1) as i64)?;
    }
    tx.commit()?;
    Ok(())
}

#[cfg(test)]
pub fn latest_version() -> usize {
    MIGRATIONS.len()
}
