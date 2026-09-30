use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{Map, Value};

use super::error::{DbError, DbResult};
use super::now_ms;

pub fn get(conn: &Connection, key: &str) -> DbResult<Option<Value>> {
    let text: Option<String> = conn
        .query_row("SELECT value_json FROM app_settings WHERE key = ?1", [key], |r| r.get(0))
        .optional()?;
    Ok(text.map(|t| serde_json::from_str(&t)).transpose()?)
}

pub fn set(conn: &Connection, key: &str, value: &Value) -> DbResult<()> {
    if key.trim().is_empty() {
        return Err(DbError::Invalid("setting key is required".into()));
    }
    conn.execute(
        "INSERT INTO app_settings (key, value_json, updated_at) VALUES (?1, ?2, ?3) \
         ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
        params![key, serde_json::to_string(value)?, now_ms()],
    )?;
    Ok(())
}

pub fn delete(conn: &Connection, key: &str) -> DbResult<bool> {
    Ok(conn.execute("DELETE FROM app_settings WHERE key = ?1", [key])? > 0)
}

/// All settings, or only keys starting with `prefix`.
pub fn list(conn: &Connection, prefix: Option<&str>) -> DbResult<Map<String, Value>> {
    let mut stmt = conn.prepare("SELECT key, value_json FROM app_settings ORDER BY key")?;
    let rows = stmt.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))?;
    let mut out = Map::new();
    for row in rows {
        let (k, v) = row?;
        if prefix.map_or(true, |p| k.starts_with(p)) {
            out.insert(k, serde_json::from_str(&v)?);
        }
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::db::open_in_memory;
    use serde_json::json;

    #[test]
    fn crud() {
        let conn = open_in_memory().unwrap();
        assert!(get(&conn, "ui.theme").unwrap().is_none());
        set(&conn, "ui.theme", &json!("dark")).unwrap();
        set(&conn, "ui.theme", &json!("light")).unwrap();
        set(&conn, "migrated.recents", &json!(true)).unwrap();
        assert_eq!(get(&conn, "ui.theme").unwrap().unwrap(), json!("light"));
        assert_eq!(list(&conn, None).unwrap().len(), 2);
        assert_eq!(list(&conn, Some("ui.")).unwrap().len(), 1);
        assert!(delete(&conn, "ui.theme").unwrap());
        assert!(!delete(&conn, "ui.theme").unwrap());
        assert_eq!(set(&conn, " ", &json!(1)).unwrap_err().code(), "invalid");
    }
}
