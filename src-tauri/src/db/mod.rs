pub mod app_settings;
pub mod commands;
pub mod error;
pub mod import;
pub mod migrations;
pub mod models;
pub mod projects;
pub mod route_cache;
pub mod settings;
pub mod versions;

use std::path::Path;
use std::sync::Mutex;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use rusqlite::Connection;

pub use error::DbResult;

pub struct DbState(pub Mutex<Connection>);

pub fn open(path: &Path) -> DbResult<Connection> {
    let mut conn = Connection::open(path)?;
    conn.pragma_update_and_check(None, "journal_mode", "WAL", |r| r.get::<_, String>(0))?;
    configure(&mut conn)?;
    Ok(conn)
}

#[cfg(test)]
pub fn open_in_memory() -> DbResult<Connection> {
    let mut conn = Connection::open_in_memory()?;
    configure(&mut conn)?;
    Ok(conn)
}

fn configure(conn: &mut Connection) -> DbResult<()> {
    conn.pragma_update(None, "foreign_keys", "ON")?;
    conn.busy_timeout(Duration::from_millis(5000))?;
    migrations::migrate(conn)
}

pub fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

// Parses a JSON text column inside a row mapper.
pub(crate) fn json_col(idx: usize, text: String) -> rusqlite::Result<serde_json::Value> {
    serde_json::from_str(&text).map_err(|e| {
        rusqlite::Error::FromSqlConversionFailure(idx, rusqlite::types::Type::Text, Box::new(e))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn file_db_persists_across_reopen() {
        let dir = std::env::temp_dir().join(format!("navivi-db-test-{}", now_ms()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("navivi.db");
        {
            let conn = open(&path).unwrap();
            app_settings::set(&conn, "k", &serde_json::json!(1)).unwrap();
        }
        let conn = open(&path).unwrap();
        let mode: String = conn.query_row("PRAGMA journal_mode", [], |r| r.get(0)).unwrap();
        assert_eq!(mode, "wal");
        assert_eq!(app_settings::get(&conn, "k").unwrap().unwrap(), 1);
        drop(conn);
        let _ = std::fs::remove_dir_all(&dir);
    }
}
