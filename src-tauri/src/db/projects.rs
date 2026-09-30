use rusqlite::types::ToSql;
use rusqlite::{params, Connection, OptionalExtension, Row};

use super::error::{is_constraint, DbError, DbResult};
use super::models::{Project, ProjectInput, ProjectPatch, ProjectQuery, ProjectSort};
use super::{json_col, now_ms};

const COLS: &str = "id, user_id, name, theme, status, directory_path, archive_path, thumbnail_path, \
    video_title, video_subtitle, enable_intro, overview_narration, overview_narration_is_auto, \
    overview_narration_source_ids, created_at, updated_at, last_opened_at, deleted_at";

const NOW_ISO: &str = "strftime('%Y-%m-%dT%H:%M:%fZ','now')";

fn from_row(r: &Row) -> rusqlite::Result<Project> {
    Ok(Project {
        id: r.get(0)?,
        user_id: r.get(1)?,
        name: r.get(2)?,
        theme: r.get(3)?,
        status: r.get(4)?,
        directory_path: r.get(5)?,
        archive_path: r.get(6)?,
        thumbnail_path: r.get(7)?,
        video_title: r.get(8)?,
        video_subtitle: r.get(9)?,
        enable_intro: r.get(10)?,
        overview_narration: r.get(11)?,
        overview_narration_is_auto: r.get(12)?,
        overview_narration_source_ids: json_col(13, r.get(13)?)?,
        created_at: r.get(14)?,
        updated_at: r.get(15)?,
        last_opened_at: r.get(16)?,
        deleted_at: r.get(17)?,
    })
}

fn validate(input: &ProjectInput) -> DbResult<()> {
    if input.id.trim().is_empty() {
        return Err(DbError::Invalid("project id is required".into()));
    }
    if input.directory_path.trim().is_empty() {
        return Err(DbError::Invalid("project directoryPath is required".into()));
    }
    Ok(())
}

fn conflict(e: rusqlite::Error, input: &ProjectInput) -> DbError {
    if is_constraint(&e) {
        DbError::Conflict(format!(
            "a project with id '{}' or directory '{}' already exists",
            input.id, input.directory_path
        ))
    } else {
        e.into()
    }
}

pub fn get(conn: &Connection, id: &str) -> DbResult<Project> {
    find(conn, id)?.ok_or_else(|| DbError::NotFound(format!("project '{id}'")))
}

pub fn find(conn: &Connection, id: &str) -> DbResult<Option<Project>> {
    Ok(conn
        .query_row(&format!("SELECT {COLS} FROM projects WHERE id = ?1"), [id], from_row)
        .optional()?)
}

pub fn get_by_dir(conn: &Connection, dir: &str) -> DbResult<Option<Project>> {
    Ok(conn
        .query_row(
            &format!("SELECT {COLS} FROM projects WHERE directory_path = ?1"),
            [dir],
            from_row,
        )
        .optional()?)
}

pub fn create(conn: &Connection, input: &ProjectInput) -> DbResult<Project> {
    validate(input)?;
    let sources = serde_json::to_string(&input.overview_narration_source_ids)?;
    conn.execute(
        &format!(
            "INSERT INTO projects (id, user_id, name, theme, status, directory_path, archive_path, \
             thumbnail_path, video_title, video_subtitle, enable_intro, overview_narration, \
             overview_narration_is_auto, overview_narration_source_ids, created_at, updated_at) \
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, COALESCE(?15, {NOW_ISO}), ?16)"
        ),
        params![
            input.id,
            input.user_id,
            input.name,
            input.theme,
            input.status,
            input.directory_path,
            input.archive_path,
            input.thumbnail_path,
            input.video_title,
            input.video_subtitle,
            input.enable_intro,
            input.overview_narration,
            input.overview_narration_is_auto,
            sources,
            input.created_at,
            now_ms(),
        ],
    )
    .map_err(|e| conflict(e, input))?;
    get(conn, &input.id)
}

/// Insert or overwrite by id. Keeps created_at and last_opened_at, and un-deletes the row.
pub fn upsert(conn: &Connection, input: &ProjectInput) -> DbResult<Project> {
    validate(input)?;
    let sources = serde_json::to_string(&input.overview_narration_source_ids)?;
    conn.execute(
        &format!(
            "INSERT INTO projects (id, user_id, name, theme, status, directory_path, archive_path, \
             thumbnail_path, video_title, video_subtitle, enable_intro, overview_narration, \
             overview_narration_is_auto, overview_narration_source_ids, created_at, updated_at) \
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, COALESCE(?15, {NOW_ISO}), ?16) \
             ON CONFLICT(id) DO UPDATE SET user_id = excluded.user_id, name = excluded.name, \
             theme = excluded.theme, status = excluded.status, directory_path = excluded.directory_path, \
             archive_path = excluded.archive_path, thumbnail_path = excluded.thumbnail_path, \
             video_title = excluded.video_title, video_subtitle = excluded.video_subtitle, \
             enable_intro = excluded.enable_intro, overview_narration = excluded.overview_narration, \
             overview_narration_is_auto = excluded.overview_narration_is_auto, \
             overview_narration_source_ids = excluded.overview_narration_source_ids, \
             updated_at = excluded.updated_at, deleted_at = NULL"
        ),
        params![
            input.id,
            input.user_id,
            input.name,
            input.theme,
            input.status,
            input.directory_path,
            input.archive_path,
            input.thumbnail_path,
            input.video_title,
            input.video_subtitle,
            input.enable_intro,
            input.overview_narration,
            input.overview_narration_is_auto,
            sources,
            input.created_at,
            now_ms(),
        ],
    )
    .map_err(|e| conflict(e, input))?;
    get(conn, &input.id)
}

pub fn list(conn: &Connection, q: &ProjectQuery) -> DbResult<Vec<Project>> {
    let mut sql = format!("SELECT {COLS} FROM projects WHERE 1 = 1");
    let mut args: Vec<Box<dyn ToSql>> = Vec::new();
    if q.only_deleted {
        sql.push_str(" AND deleted_at IS NOT NULL");
    } else if !q.include_deleted {
        sql.push_str(" AND deleted_at IS NULL");
    }
    if let Some(s) = q.search.as_deref().map(str::trim).filter(|s| !s.is_empty()) {
        let escaped = s.replace('\\', "\\\\").replace('%', "\\%").replace('_', "\\_");
        sql.push_str(" AND (name LIKE ? ESCAPE '\\' OR video_title LIKE ? ESCAPE '\\')");
        let pattern = format!("%{escaped}%");
        args.push(Box::new(pattern.clone()));
        args.push(Box::new(pattern));
    }
    sql.push_str(match q.sort {
        ProjectSort::Recent => {
            " ORDER BY last_opened_at IS NULL, last_opened_at DESC, updated_at DESC"
        }
        ProjectSort::Name => " ORDER BY name COLLATE NOCASE ASC",
        ProjectSort::Updated => " ORDER BY updated_at DESC",
        ProjectSort::Created => " ORDER BY created_at DESC",
    });
    sql.push_str(" LIMIT ? OFFSET ?");
    args.push(Box::new(q.limit.unwrap_or(-1)));
    args.push(Box::new(q.offset.unwrap_or(0).max(0)));

    let mut stmt = conn.prepare(&sql)?;
    let rows = stmt.query_map(rusqlite::params_from_iter(args.iter()), from_row)?;
    Ok(rows.collect::<Result<Vec<_>, _>>()?)
}

pub fn update(conn: &Connection, id: &str, patch: &ProjectPatch) -> DbResult<Project> {
    let mut sets: Vec<&str> = Vec::new();
    let mut args: Vec<Box<dyn ToSql>> = Vec::new();
    macro_rules! set {
        ($field:expr, $col:literal) => {
            if let Some(v) = $field.clone() {
                sets.push(concat!($col, " = ?"));
                args.push(Box::new(v));
            }
        };
    }
    set!(patch.user_id, "user_id");
    set!(patch.name, "name");
    set!(patch.theme, "theme");
    set!(patch.status, "status");
    set!(patch.directory_path, "directory_path");
    set!(patch.archive_path, "archive_path");
    set!(patch.thumbnail_path, "thumbnail_path");
    set!(patch.video_title, "video_title");
    set!(patch.video_subtitle, "video_subtitle");
    set!(patch.enable_intro, "enable_intro");
    set!(patch.overview_narration, "overview_narration");
    set!(patch.overview_narration_is_auto, "overview_narration_is_auto");
    if let Some(v) = &patch.overview_narration_source_ids {
        sets.push("overview_narration_source_ids = ?");
        args.push(Box::new(serde_json::to_string(v)?));
    }
    sets.push("updated_at = ?");
    args.push(Box::new(now_ms()));
    args.push(Box::new(id.to_string()));

    let sql = format!("UPDATE projects SET {} WHERE id = ?", sets.join(", "));
    let changed = conn
        .execute(&sql, rusqlite::params_from_iter(args.iter()))
        .map_err(|e| {
            if is_constraint(&e) {
                DbError::Conflict("another project already uses that directory".into())
            } else {
                e.into()
            }
        })?;
    if changed == 0 {
        return Err(DbError::NotFound(format!("project '{id}'")));
    }
    get(conn, id)
}

pub fn touch_opened(conn: &Connection, id: &str) -> DbResult<Project> {
    let changed = conn.execute(
        "UPDATE projects SET last_opened_at = ?1 WHERE id = ?2",
        params![now_ms(), id],
    )?;
    if changed == 0 {
        return Err(DbError::NotFound(format!("project '{id}'")));
    }
    get(conn, id)
}

/// Removes the project from the recents list without deleting its data.
pub fn forget_opened(conn: &Connection, id: &str) -> DbResult<bool> {
    Ok(conn.execute("UPDATE projects SET last_opened_at = NULL WHERE id = ?1", [id])? > 0)
}

pub fn soft_delete(conn: &Connection, id: &str) -> DbResult<bool> {
    Ok(conn.execute(
        "UPDATE projects SET deleted_at = ?1 WHERE id = ?2 AND deleted_at IS NULL",
        params![now_ms(), id],
    )? > 0)
}

pub fn restore(conn: &Connection, id: &str) -> DbResult<bool> {
    Ok(conn.execute(
        "UPDATE projects SET deleted_at = NULL WHERE id = ?1 AND deleted_at IS NOT NULL",
        [id],
    )? > 0)
}

/// Hard delete; settings, versions and route cache cascade.
pub fn purge(conn: &Connection, id: &str) -> DbResult<bool> {
    Ok(conn.execute("DELETE FROM projects WHERE id = ?1", [id])? > 0)
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use crate::db::open_in_memory;

    pub fn input(id: &str) -> ProjectInput {
        serde_json::from_value(serde_json::json!({
            "id": id,
            "name": format!("Project {id}"),
            "directoryPath": format!("C:/ws/{id}"),
        }))
        .unwrap()
    }

    #[test]
    fn create_get_and_defaults() {
        let conn = open_in_memory().unwrap();
        let p = create(&conn, &input("a")).unwrap();
        assert_eq!(p.status, "saved");
        assert!(p.enable_intro);
        assert!(p.created_at.ends_with('Z'));
        assert_eq!(p.overview_narration_source_ids, serde_json::json!([]));
        assert_eq!(get(&conn, "a").unwrap(), p);
        assert_eq!(get_by_dir(&conn, "C:/ws/a").unwrap().unwrap().id, "a");
    }

    #[test]
    fn create_duplicate_is_conflict() {
        let conn = open_in_memory().unwrap();
        create(&conn, &input("a")).unwrap();
        let err = create(&conn, &input("a")).unwrap_err();
        assert_eq!(err.code(), "conflict");
        let mut other = input("b");
        other.directory_path = "C:/ws/a".into();
        assert_eq!(create(&conn, &other).unwrap_err().code(), "conflict");
    }

    #[test]
    fn get_missing_is_not_found() {
        let conn = open_in_memory().unwrap();
        assert_eq!(get(&conn, "nope").unwrap_err().code(), "not_found");
    }

    #[test]
    fn upsert_keeps_created_and_undeletes() {
        let conn = open_in_memory().unwrap();
        let first = upsert(&conn, &input("a")).unwrap();
        touch_opened(&conn, "a").unwrap();
        soft_delete(&conn, "a").unwrap();
        let mut changed = input("a");
        changed.name = "Renamed".into();
        changed.created_at = Some("1999-01-01T00:00:00Z".into());
        let second = upsert(&conn, &changed).unwrap();
        assert_eq!(second.name, "Renamed");
        assert_eq!(second.created_at, first.created_at);
        assert!(second.last_opened_at.is_some());
        assert!(second.deleted_at.is_none());
    }

    #[test]
    fn update_patch_and_clear() {
        let conn = open_in_memory().unwrap();
        let mut i = input("a");
        i.thumbnail_path = Some("thumb.png".into());
        create(&conn, &i).unwrap();
        let patch: ProjectPatch = serde_json::from_value(serde_json::json!({
            "videoTitle": "Tokyo", "enableIntro": false, "thumbnailPath": null,
            "overviewNarrationSourceIds": ["w1", "w2"]
        }))
        .unwrap();
        let p = update(&conn, "a", &patch).unwrap();
        assert_eq!(p.video_title, "Tokyo");
        assert!(!p.enable_intro);
        assert_eq!(p.thumbnail_path, None);
        assert_eq!(p.name, "Project a");
        assert_eq!(p.overview_narration_source_ids, serde_json::json!(["w1", "w2"]));
        assert_eq!(update(&conn, "zz", &patch).unwrap_err().code(), "not_found");
    }

    #[test]
    fn list_filters_sorts_and_pages() {
        let conn = open_in_memory().unwrap();
        for id in ["c", "a", "b"] {
            create(&conn, &input(id)).unwrap();
        }
        touch_opened(&conn, "b").unwrap();
        soft_delete(&conn, "c").unwrap();

        let recent = list(&conn, &ProjectQuery::default()).unwrap();
        assert_eq!(recent.iter().map(|p| p.id.as_str()).collect::<Vec<_>>(), ["b", "a"]);

        let q = ProjectQuery { sort: ProjectSort::Name, include_deleted: true, ..Default::default() };
        let names = list(&conn, &q).unwrap();
        assert_eq!(names.iter().map(|p| p.id.as_str()).collect::<Vec<_>>(), ["a", "b", "c"]);

        let q = ProjectQuery { only_deleted: true, ..Default::default() };
        assert_eq!(list(&conn, &q).unwrap()[0].id, "c");

        let q = ProjectQuery { search: Some("project b".into()), ..Default::default() };
        assert_eq!(list(&conn, &q).unwrap().len(), 1);

        let q = ProjectQuery { search: Some("%".into()), ..Default::default() };
        assert!(list(&conn, &q).unwrap().is_empty());

        let q = ProjectQuery { sort: ProjectSort::Name, limit: Some(1), offset: Some(1), ..Default::default() };
        assert_eq!(list(&conn, &q).unwrap()[0].id, "b");
    }

    #[test]
    fn delete_restore_purge() {
        let conn = open_in_memory().unwrap();
        create(&conn, &input("a")).unwrap();
        assert!(soft_delete(&conn, "a").unwrap());
        assert!(!soft_delete(&conn, "a").unwrap());
        assert!(restore(&conn, "a").unwrap());
        assert!(purge(&conn, "a").unwrap());
        assert!(find(&conn, "a").unwrap().is_none());
        assert!(!purge(&conn, "a").unwrap());
    }
}
