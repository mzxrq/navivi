use rusqlite::Connection;
use serde_json::{Map, Value};
use tauri::State;

use super::error::{DbError, DbResult};
use super::models::*;
use super::{app_settings, import, projects, route_cache, settings, versions, DbState};

fn with<T>(state: &State<'_, DbState>, f: impl FnOnce(&Connection) -> DbResult<T>) -> DbResult<T> {
    let conn = state
        .0
        .lock()
        .map_err(|_| DbError::Invalid("database lock poisoned".into()))?;
    f(&conn)
}

// Projects

#[tauri::command]
pub async fn project_upsert(state: State<'_, DbState>, input: ProjectInput) -> DbResult<Project> {
    with(&state, |c| projects::upsert(c, &input))
}

#[tauri::command]
pub async fn project_get(state: State<'_, DbState>, id: String) -> DbResult<Option<Project>> {
    with(&state, |c| projects::find(c, &id))
}

#[tauri::command]
pub async fn project_list(state: State<'_, DbState>, query: Option<ProjectQuery>) -> DbResult<Vec<Project>> {
    with(&state, |c| projects::list(c, &query.unwrap_or_default()))
}

#[tauri::command]
pub async fn project_update(state: State<'_, DbState>, id: String, patch: ProjectPatch) -> DbResult<Project> {
    with(&state, |c| projects::update(c, &id, &patch))
}

#[tauri::command]
pub async fn project_touch_opened(state: State<'_, DbState>, id: String) -> DbResult<Project> {
    with(&state, |c| projects::touch_opened(c, &id))
}

#[tauri::command]
pub async fn project_forget_opened(state: State<'_, DbState>, id: String) -> DbResult<bool> {
    with(&state, |c| projects::forget_opened(c, &id))
}

#[tauri::command]
pub async fn project_import_legacy(state: State<'_, DbState>, data: LegacyImport) -> DbResult<ImportReport> {
    with(&state, |c| import::import_legacy(c, &data))
}

// Settings

#[tauri::command]
pub async fn settings_get(state: State<'_, DbState>, project_id: String) -> DbResult<Option<Value>> {
    with(&state, |c| settings::get(c, &project_id))
}

#[tauri::command]
pub async fn settings_put(state: State<'_, DbState>, project_id: String, settings: Value) -> DbResult<Value> {
    with(&state, |c| settings::put(c, &project_id, &settings))
}

#[tauri::command]
pub async fn settings_patch(state: State<'_, DbState>, project_id: String, patch: Value) -> DbResult<Value> {
    with(&state, |c| settings::patch(c, &project_id, &patch))
}

// Versions

#[tauri::command]
pub async fn version_create(state: State<'_, DbState>, version: Version) -> DbResult<VersionMeta> {
    with(&state, |c| versions::create(c, &version))
}

#[tauri::command]
pub async fn version_list(state: State<'_, DbState>, project_id: String) -> DbResult<Vec<VersionMeta>> {
    with(&state, |c| versions::list(c, &project_id))
}

#[tauri::command]
pub async fn version_get(state: State<'_, DbState>, project_id: String, id: String) -> DbResult<Option<Version>> {
    with(&state, |c| match versions::get(c, &project_id, &id) {
        Ok(v) => Ok(Some(v)),
        Err(DbError::NotFound(_)) => Ok(None),
        Err(e) => Err(e),
    })
}

#[tauri::command]
pub async fn version_rename(state: State<'_, DbState>, project_id: String, id: String, label: String) -> DbResult<VersionMeta> {
    with(&state, |c| versions::rename(c, &project_id, &id, &label))
}

#[tauri::command]
pub async fn version_delete(state: State<'_, DbState>, project_id: String, id: String) -> DbResult<bool> {
    with(&state, |c| versions::delete(c, &project_id, &id))
}

// Route cache

#[tauri::command]
pub async fn route_cache_get_all(state: State<'_, DbState>, project_id: String) -> DbResult<Map<String, Value>> {
    with(&state, |c| route_cache::get_all(c, &project_id))
}

#[tauri::command]
pub async fn route_cache_replace(state: State<'_, DbState>, project_id: String, entries: Map<String, Value>) -> DbResult<usize> {
    with(&state, |c| route_cache::replace(c, &project_id, &entries))
}

// App settings

#[tauri::command]
pub async fn app_setting_get(state: State<'_, DbState>, key: String) -> DbResult<Option<Value>> {
    with(&state, |c| app_settings::get(c, &key))
}

#[tauri::command]
pub async fn app_setting_set(state: State<'_, DbState>, key: String, value: Value) -> DbResult<()> {
    with(&state, |c| app_settings::set(c, &key, &value))
}
