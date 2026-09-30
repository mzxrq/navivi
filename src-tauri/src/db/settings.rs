use rusqlite::{params, Connection, OptionalExtension};
use serde_json::Value;

use super::error::{DbError, DbResult};
use super::{now_ms, projects};

fn require_object(v: &Value) -> DbResult<()> {
    if v.is_object() {
        Ok(())
    } else {
        Err(DbError::Invalid("settings must be a JSON object".into()))
    }
}

pub fn get(conn: &Connection, project_id: &str) -> DbResult<Option<Value>> {
    let text: Option<String> = conn
        .query_row(
            "SELECT settings_json FROM project_settings WHERE project_id = ?1",
            [project_id],
            |r| r.get(0),
        )
        .optional()?;
    Ok(text.map(|t| serde_json::from_str(&t)).transpose()?)
}

/// Create or replace the whole settings document.
pub fn put(conn: &Connection, project_id: &str, settings: &Value) -> DbResult<Value> {
    require_object(settings)?;
    projects::get(conn, project_id)?;
    conn.execute(
        "INSERT INTO project_settings (project_id, settings_json, updated_at) VALUES (?1, ?2, ?3) \
         ON CONFLICT(project_id) DO UPDATE SET settings_json = excluded.settings_json, updated_at = excluded.updated_at",
        params![project_id, serde_json::to_string(settings)?, now_ms()],
    )?;
    Ok(settings.clone())
}

/// RFC 7396 merge: nested objects merge, a `null` value removes that key.
pub fn patch(conn: &Connection, project_id: &str, partial: &Value) -> DbResult<Value> {
    require_object(partial)?;
    let changed = conn.execute(
        "UPDATE project_settings SET settings_json = json_patch(settings_json, ?1), updated_at = ?2 \
         WHERE project_id = ?3",
        params![serde_json::to_string(partial)?, now_ms(), project_id],
    )?;
    if changed == 0 {
        return Err(DbError::NotFound(format!("settings for project '{project_id}'")));
    }
    get(conn, project_id)?.ok_or_else(|| DbError::NotFound(format!("settings for '{project_id}'")))
}

pub fn delete(conn: &Connection, project_id: &str) -> DbResult<bool> {
    Ok(conn.execute("DELETE FROM project_settings WHERE project_id = ?1", [project_id])? > 0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::db::open_in_memory;
    use crate::db::projects::tests::input;
    use serde_json::json;

    #[test]
    fn put_get_patch_delete() {
        let conn = open_in_memory().unwrap();
        projects::create(&conn, &input("a")).unwrap();
        assert!(get(&conn, "a").unwrap().is_none());

        put(&conn, "a", &json!({"fps": 30, "line_color": [1, 2, 3], "subtitle": {"size": 20, "bold": true}})).unwrap();
        let merged = patch(&conn, "a", &json!({"fps": 60, "subtitle": {"size": 24}, "line_color": null})).unwrap();
        assert_eq!(merged, json!({"fps": 60, "subtitle": {"size": 24, "bold": true}}));

        put(&conn, "a", &json!({"fps": 24})).unwrap();
        assert_eq!(get(&conn, "a").unwrap().unwrap(), json!({"fps": 24}));

        assert!(delete(&conn, "a").unwrap());
        assert_eq!(patch(&conn, "a", &json!({})).unwrap_err().code(), "not_found");
    }

    #[test]
    fn rejects_non_object_and_unknown_project() {
        let conn = open_in_memory().unwrap();
        projects::create(&conn, &input("a")).unwrap();
        assert_eq!(put(&conn, "a", &json!([1])).unwrap_err().code(), "invalid");
        assert_eq!(put(&conn, "zz", &json!({})).unwrap_err().code(), "not_found");
    }

    #[test]
    fn purge_cascades() {
        let conn = open_in_memory().unwrap();
        projects::create(&conn, &input("a")).unwrap();
        put(&conn, "a", &json!({"fps": 30})).unwrap();
        projects::purge(&conn, "a").unwrap();
        assert!(get(&conn, "a").unwrap().is_none());
    }
}
