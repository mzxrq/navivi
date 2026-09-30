use std::collections::HashSet;

use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{Map, Value};

use super::error::{DbError, DbResult};
use super::{now_ms, projects};

pub(crate) fn insert(conn: &Connection, project_id: &str, key: &str, points: &Value, replace: bool) -> DbResult<bool> {
    if !points.is_array() {
        return Err(DbError::Invalid(format!("route '{key}' points must be an array")));
    }
    let sql = if replace {
        "INSERT INTO route_cache (project_id, cache_key, points_json, updated_at) VALUES (?1, ?2, ?3, ?4) \
         ON CONFLICT(project_id, cache_key) DO UPDATE SET points_json = excluded.points_json, updated_at = excluded.updated_at"
    } else {
        "INSERT OR IGNORE INTO route_cache (project_id, cache_key, points_json, updated_at) VALUES (?1, ?2, ?3, ?4)"
    };
    Ok(conn.execute(sql, params![project_id, key, serde_json::to_string(points)?, now_ms()])? > 0)
}

pub fn get_all(conn: &Connection, project_id: &str) -> DbResult<Map<String, Value>> {
    let mut stmt = conn.prepare("SELECT cache_key, points_json FROM route_cache WHERE project_id = ?1")?;
    let rows = stmt.query_map([project_id], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))?;
    let mut out = Map::new();
    for row in rows {
        let (k, v) = row?;
        out.insert(k, serde_json::from_str(&v)?);
    }
    Ok(out)
}

pub fn get(conn: &Connection, project_id: &str, key: &str) -> DbResult<Option<Value>> {
    let text: Option<String> = conn
        .query_row(
            "SELECT points_json FROM route_cache WHERE project_id = ?1 AND cache_key = ?2",
            [project_id, key],
            |r| r.get(0),
        )
        .optional()?;
    Ok(text.map(|t| serde_json::from_str(&t)).transpose()?)
}

pub fn put(conn: &Connection, project_id: &str, key: &str, points: &Value) -> DbResult<()> {
    projects::get(conn, project_id)?;
    insert(conn, project_id, key, points, true)?;
    Ok(())
}

pub fn put_many(conn: &Connection, project_id: &str, entries: &Map<String, Value>) -> DbResult<usize> {
    projects::get(conn, project_id)?;
    let tx = conn.unchecked_transaction()?;
    for (k, v) in entries {
        insert(&tx, project_id, k, v, true)?;
    }
    tx.commit()?;
    Ok(entries.len())
}

/// Makes the cache exactly `entries`: drops every other key, upserts the rest.
pub fn replace(conn: &Connection, project_id: &str, entries: &Map<String, Value>) -> DbResult<usize> {
    projects::get(conn, project_id)?;
    let tx = conn.unchecked_transaction()?;
    let keep: Vec<String> = entries.keys().cloned().collect();
    prune_inner(&tx, project_id, &keep)?;
    for (k, v) in entries {
        insert(&tx, project_id, k, v, true)?;
    }
    tx.commit()?;
    Ok(entries.len())
}

pub fn delete(conn: &Connection, project_id: &str, key: &str) -> DbResult<bool> {
    Ok(conn.execute(
        "DELETE FROM route_cache WHERE project_id = ?1 AND cache_key = ?2",
        [project_id, key],
    )? > 0)
}

fn prune_inner(conn: &Connection, project_id: &str, keep: &[String]) -> DbResult<usize> {
    let keep: HashSet<&str> = keep.iter().map(String::as_str).collect();
    let keys: Vec<String> = {
        let mut stmt = conn.prepare("SELECT cache_key FROM route_cache WHERE project_id = ?1")?;
        let rows = stmt.query_map([project_id], |r| r.get(0))?;
        rows.collect::<Result<_, _>>()?
    };
    let mut removed = 0;
    for key in keys.iter().filter(|k| !keep.contains(k.as_str())) {
        removed += conn.execute(
            "DELETE FROM route_cache WHERE project_id = ?1 AND cache_key = ?2",
            [project_id, key.as_str()],
        )?;
    }
    Ok(removed)
}

/// Deletes every key not in `keep`; returns how many were removed.
pub fn prune(conn: &Connection, project_id: &str, keep: &[String]) -> DbResult<usize> {
    let tx = conn.unchecked_transaction()?;
    let removed = prune_inner(&tx, project_id, keep)?;
    tx.commit()?;
    Ok(removed)
}

pub fn clear(conn: &Connection, project_id: &str) -> DbResult<usize> {
    Ok(conn.execute("DELETE FROM route_cache WHERE project_id = ?1", [project_id])?)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::db::open_in_memory;
    use crate::db::projects::tests::input;
    use serde_json::json;

    fn map(v: Value) -> Map<String, Value> {
        v.as_object().unwrap().clone()
    }

    #[test]
    fn crud_prune_replace() {
        let conn = open_in_memory().unwrap();
        projects::create(&conn, &input("a")).unwrap();

        put(&conn, "a", "k1", &json!([[1.0, 2.0]])).unwrap();
        put(&conn, "a", "k1", &json!([[3.0, 4.0]])).unwrap();
        assert_eq!(get(&conn, "a", "k1").unwrap().unwrap(), json!([[3.0, 4.0]]));
        assert!(get(&conn, "a", "nope").unwrap().is_none());

        put_many(&conn, "a", &map(json!({"k2": [], "k3": [[0, 0]]}))).unwrap();
        assert_eq!(get_all(&conn, "a").unwrap().len(), 3);

        assert_eq!(prune(&conn, "a", &["k1".into(), "k3".into()]).unwrap(), 1);
        assert!(delete(&conn, "a", "k3").unwrap());
        assert!(!delete(&conn, "a", "k3").unwrap());

        replace(&conn, "a", &map(json!({"k9": [[9, 9]]}))).unwrap();
        assert_eq!(get_all(&conn, "a").unwrap(), map(json!({"k9": [[9, 9]]})));

        assert_eq!(clear(&conn, "a").unwrap(), 1);
    }

    #[test]
    fn validates() {
        let conn = open_in_memory().unwrap();
        projects::create(&conn, &input("a")).unwrap();
        assert_eq!(put(&conn, "a", "k", &json!({"x": 1})).unwrap_err().code(), "invalid");
        assert_eq!(put(&conn, "zz", "k", &json!([])).unwrap_err().code(), "not_found");
    }
}
