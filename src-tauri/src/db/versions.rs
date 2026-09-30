use rusqlite::{params, Connection, OptionalExtension, Row};

use super::error::{is_constraint, DbError, DbResult};
use super::json_col;
use super::models::{Version, VersionMeta};
use super::projects;

pub const MAX_VERSIONS: i64 = 30;

const META_COLS: &str = "id, project_id, project_name, label, created_at, waypoint_count, clip_count";

fn meta_from_row(r: &Row) -> rusqlite::Result<VersionMeta> {
    Ok(VersionMeta {
        id: r.get(0)?,
        project_id: r.get(1)?,
        project_name: r.get(2)?,
        label: r.get(3)?,
        created_at: r.get(4)?,
        waypoint_count: r.get(5)?,
        clip_count: r.get(6)?,
    })
}

/// Insert without a transaction; returns false if the id already exists and `ignore_existing`.
pub(crate) fn insert(conn: &Connection, v: &Version, ignore_existing: bool) -> DbResult<bool> {
    let m = &v.meta;
    if m.id.trim().is_empty() {
        return Err(DbError::Invalid("version id is required".into()));
    }
    if m.label.trim().is_empty() {
        return Err(DbError::Invalid("version label is required".into()));
    }
    let verb = if ignore_existing { "INSERT OR IGNORE" } else { "INSERT" };
    let changed = conn
        .execute(
            &format!("{verb} INTO project_versions ({META_COLS}, snapshot_json) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)"),
            params![
                m.id,
                m.project_id,
                m.project_name,
                m.label.trim(),
                m.created_at,
                m.waypoint_count,
                m.clip_count,
                serde_json::to_string(&v.snapshot)?,
            ],
        )
        .map_err(|e| {
            if is_constraint(&e) {
                DbError::Conflict(format!("version '{}' already exists", m.id))
            } else {
                e.into()
            }
        })?;
    Ok(changed > 0)
}

pub(crate) fn prune(conn: &Connection, project_id: &str, keep: i64) -> DbResult<usize> {
    Ok(conn.execute(
        "DELETE FROM project_versions WHERE project_id = ?1 AND id NOT IN (\
         SELECT id FROM project_versions WHERE project_id = ?1 \
         ORDER BY created_at DESC, rowid DESC LIMIT ?2)",
        params![project_id, keep],
    )?)
}

/// Insert and prune to the newest MAX_VERSIONS, atomically.
pub fn create(conn: &Connection, v: &Version) -> DbResult<VersionMeta> {
    projects::get(conn, &v.meta.project_id)?;
    let tx = conn.unchecked_transaction()?;
    insert(&tx, v, false)?;
    prune(&tx, &v.meta.project_id, MAX_VERSIONS)?;
    tx.commit()?;
    Ok(v.meta.clone())
}

pub fn list(conn: &Connection, project_id: &str) -> DbResult<Vec<VersionMeta>> {
    let mut stmt = conn.prepare(&format!(
        "SELECT {META_COLS} FROM project_versions WHERE project_id = ?1 ORDER BY created_at DESC, rowid DESC"
    ))?;
    let rows = stmt.query_map([project_id], meta_from_row)?;
    Ok(rows.collect::<Result<Vec<_>, _>>()?)
}

pub fn get(conn: &Connection, project_id: &str, id: &str) -> DbResult<Version> {
    conn.query_row(
        &format!("SELECT {META_COLS}, snapshot_json FROM project_versions WHERE project_id = ?1 AND id = ?2"),
        [project_id, id],
        |r| Ok(Version { meta: meta_from_row(r)?, snapshot: json_col(7, r.get(7)?)? }),
    )
    .optional()?
    .ok_or_else(|| DbError::NotFound(format!("version '{id}'")))
}

pub fn rename(conn: &Connection, project_id: &str, id: &str, label: &str) -> DbResult<VersionMeta> {
    let label = label.trim();
    if label.is_empty() {
        return Err(DbError::Invalid("version label is required".into()));
    }
    let changed = conn.execute(
        "UPDATE project_versions SET label = ?1, \
         snapshot_json = CASE WHEN json_type(snapshot_json, '$.label') IS NOT NULL \
             THEN json_set(snapshot_json, '$.label', ?1) ELSE snapshot_json END \
         WHERE project_id = ?2 AND id = ?3",
        params![label, project_id, id],
    )?;
    if changed == 0 {
        return Err(DbError::NotFound(format!("version '{id}'")));
    }
    Ok(get(conn, project_id, id)?.meta)
}

pub fn delete(conn: &Connection, project_id: &str, id: &str) -> DbResult<bool> {
    Ok(conn.execute(
        "DELETE FROM project_versions WHERE project_id = ?1 AND id = ?2",
        [project_id, id],
    )? > 0)
}

pub fn delete_all(conn: &Connection, project_id: &str) -> DbResult<usize> {
    Ok(conn.execute("DELETE FROM project_versions WHERE project_id = ?1", [project_id])?)
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use crate::db::open_in_memory;
    use crate::db::projects::tests::input;
    use serde_json::json;

    pub fn version(project: &str, id: &str, created_at: &str) -> Version {
        Version {
            meta: VersionMeta {
                id: id.into(),
                project_id: project.into(),
                project_name: "P".into(),
                label: format!("v {id}"),
                created_at: created_at.into(),
                waypoint_count: 2,
                clip_count: 1,
            },
            snapshot: json!({"id": id, "label": format!("v {id}"), "waypoints": [1, 2]}),
        }
    }

    #[test]
    fn crud_round_trip() {
        let conn = open_in_memory().unwrap();
        projects::create(&conn, &input("a")).unwrap();
        create(&conn, &version("a", "v1", "2026-01-01T00:00:00Z")).unwrap();
        create(&conn, &version("a", "v2", "2026-01-02T00:00:00Z")).unwrap();

        let ids: Vec<_> = list(&conn, "a").unwrap().into_iter().map(|m| m.id).collect();
        assert_eq!(ids, ["v2", "v1"]);

        let got = get(&conn, "a", "v1").unwrap();
        assert_eq!(got.snapshot["waypoints"], json!([1, 2]));
        assert_eq!(get(&conn, "b", "v1").unwrap_err().code(), "not_found");

        let renamed = rename(&conn, "a", "v1", "  Before lunch ").unwrap();
        assert_eq!(renamed.label, "Before lunch");
        assert_eq!(get(&conn, "a", "v1").unwrap().snapshot["label"], "Before lunch");
        assert_eq!(rename(&conn, "a", "v1", " ").unwrap_err().code(), "invalid");

        assert!(delete(&conn, "a", "v1").unwrap());
        assert!(!delete(&conn, "a", "v1").unwrap());
        assert_eq!(delete_all(&conn, "a").unwrap(), 1);
    }

    #[test]
    fn duplicate_and_unknown_project() {
        let conn = open_in_memory().unwrap();
        projects::create(&conn, &input("a")).unwrap();
        create(&conn, &version("a", "v1", "2026-01-01T00:00:00Z")).unwrap();
        assert_eq!(create(&conn, &version("a", "v1", "2026-01-01T00:00:00Z")).unwrap_err().code(), "conflict");
        assert_eq!(create(&conn, &version("zz", "v9", "2026-01-01T00:00:00Z")).unwrap_err().code(), "not_found");
    }

    #[test]
    fn prunes_to_max() {
        let conn = open_in_memory().unwrap();
        projects::create(&conn, &input("a")).unwrap();
        for i in 0..=MAX_VERSIONS {
            let ts = format!("2026-01-01T00:00:{i:02}Z");
            create(&conn, &version("a", &format!("v{i}"), &ts)).unwrap();
        }
        let all = list(&conn, "a").unwrap();
        assert_eq!(all.len() as i64, MAX_VERSIONS);
        assert!(all.iter().all(|m| m.id != "v0"));
    }
}
