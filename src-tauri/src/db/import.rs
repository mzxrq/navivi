use rusqlite::{params, Connection};

use super::error::DbResult;
use super::models::{ImportReport, LegacyImport};
use super::{now_ms, projects, route_cache, versions};

/// One-time import of a pre-DB project (job_config + .history + .routecache).
/// Idempotent: existing rows win, only missing ones are added.
pub fn import_legacy(conn: &Connection, data: &LegacyImport) -> DbResult<ImportReport> {
    let tx = conn.unchecked_transaction()?;
    let id = &data.project.id;

    let created = projects::find(&tx, id)?.is_none();
    if created {
        projects::create(&tx, &data.project)?;
    }

    let mut settings_imported = false;
    if let Some(settings) = data.settings.as_ref().filter(|s| s.is_object()) {
        settings_imported = tx.execute(
            "INSERT OR IGNORE INTO project_settings (project_id, settings_json, updated_at) VALUES (?1, ?2, ?3)",
            params![id, serde_json::to_string(settings)?, now_ms()],
        )? > 0;
    }

    let mut versions_imported = 0;
    for v in data.versions.iter().filter(|v| &v.meta.project_id == id) {
        if versions::insert(&tx, v, true)? {
            versions_imported += 1;
        }
    }
    versions::prune(&tx, id, versions::MAX_VERSIONS)?;

    let mut routes_imported = 0;
    for (key, points) in &data.route_cache {
        if points.is_array() && route_cache::insert(&tx, id, key, points, false)? {
            routes_imported += 1;
        }
    }

    let project = projects::get(&tx, id)?;
    tx.commit()?;
    Ok(ImportReport { project, created, settings_imported, versions_imported, routes_imported })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::db::open_in_memory;
    use crate::db::versions::tests::version;
    use crate::db::{migrations, settings};
    use serde_json::json;

    fn legacy() -> LegacyImport {
        LegacyImport {
            project: crate::db::projects::tests::input("a"),
            settings: Some(json!({"fps": 30})),
            versions: vec![
                version("a", "v1", "2026-01-01T00:00:00Z"),
                version("other", "v2", "2026-01-01T00:00:00Z"),
            ],
            route_cache: json!({"k1": [[1, 2]], "bad": {"x": 1}}).as_object().unwrap().clone(),
        }
    }

    #[test]
    fn import_twice_is_idempotent() {
        let conn = open_in_memory().unwrap();
        let first = import_legacy(&conn, &legacy()).unwrap();
        assert!(first.created && first.settings_imported);
        assert_eq!((first.versions_imported, first.routes_imported), (1, 1));

        settings::patch(&conn, "a", &json!({"fps": 60})).unwrap();
        let second = import_legacy(&conn, &legacy()).unwrap();
        assert!(!second.created && !second.settings_imported);
        assert_eq!((second.versions_imported, second.routes_imported), (0, 0));
        assert_eq!(settings::get(&conn, "a").unwrap().unwrap()["fps"], 60);
        assert_eq!(versions::list(&conn, "a").unwrap().len(), 1);
    }

    #[test]
    fn migrations_rerun_is_noop() {
        let mut conn = open_in_memory().unwrap();
        migrations::migrate(&mut conn).unwrap();
        let v: i64 = conn.query_row("PRAGMA user_version", [], |r| r.get(0)).unwrap();
        assert_eq!(v as usize, migrations::latest_version());
    }
}
