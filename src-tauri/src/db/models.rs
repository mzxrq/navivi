use serde::{Deserialize, Deserializer, Serialize};
use serde_json::Value;

// Missing field -> None (leave as is), explicit null -> Some(None) (clear).
fn double_option<'de, D, T>(d: D) -> Result<Option<Option<T>>, D::Error>
where
    D: Deserializer<'de>,
    T: Deserialize<'de>,
{
    Option::<T>::deserialize(d).map(Some)
}

fn default_status() -> String {
    "saved".into()
}
fn default_true() -> bool {
    true
}
fn empty_array() -> Value {
    Value::Array(vec![])
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct Project {
    pub id: String,
    pub user_id: Option<String>,
    pub name: String,
    pub theme: Option<String>,
    pub status: String,
    pub directory_path: String,
    pub archive_path: Option<String>,
    pub thumbnail_path: Option<String>,
    pub video_title: String,
    pub video_subtitle: String,
    pub enable_intro: bool,
    pub overview_narration: String,
    pub overview_narration_is_auto: bool,
    pub overview_narration_source_ids: Value,
    pub created_at: String,
    pub updated_at: i64,
    pub last_opened_at: Option<i64>,
    pub deleted_at: Option<i64>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ProjectInput {
    pub id: String,
    pub name: String,
    pub directory_path: String,
    #[serde(default)]
    pub user_id: Option<String>,
    #[serde(default)]
    pub theme: Option<String>,
    #[serde(default = "default_status")]
    pub status: String,
    #[serde(default)]
    pub archive_path: Option<String>,
    #[serde(default)]
    pub thumbnail_path: Option<String>,
    #[serde(default)]
    pub video_title: String,
    #[serde(default)]
    pub video_subtitle: String,
    #[serde(default = "default_true")]
    pub enable_intro: bool,
    #[serde(default)]
    pub overview_narration: String,
    #[serde(default)]
    pub overview_narration_is_auto: bool,
    #[serde(default = "empty_array")]
    pub overview_narration_source_ids: Value,
    /// ISO string; defaults to now.
    #[serde(default)]
    pub created_at: Option<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct ProjectPatch {
    #[serde(deserialize_with = "double_option")]
    pub user_id: Option<Option<String>>,
    pub name: Option<String>,
    #[serde(deserialize_with = "double_option")]
    pub theme: Option<Option<String>>,
    pub status: Option<String>,
    pub directory_path: Option<String>,
    #[serde(deserialize_with = "double_option")]
    pub archive_path: Option<Option<String>>,
    #[serde(deserialize_with = "double_option")]
    pub thumbnail_path: Option<Option<String>>,
    pub video_title: Option<String>,
    pub video_subtitle: Option<String>,
    pub enable_intro: Option<bool>,
    pub overview_narration: Option<String>,
    pub overview_narration_is_auto: Option<bool>,
    pub overview_narration_source_ids: Option<Value>,
}

#[derive(Debug, Clone, Copy, Default, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum ProjectSort {
    #[default]
    Recent,
    Name,
    Updated,
    Created,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct ProjectQuery {
    pub search: Option<String>,
    pub include_deleted: bool,
    pub only_deleted: bool,
    pub sort: ProjectSort,
    pub limit: Option<i64>,
    pub offset: Option<i64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct VersionMeta {
    pub id: String,
    pub project_id: String,
    pub project_name: String,
    pub label: String,
    pub created_at: String,
    pub waypoint_count: i64,
    pub clip_count: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct Version {
    #[serde(flatten)]
    pub meta: VersionMeta,
    pub snapshot: Value,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LegacyImport {
    pub project: ProjectInput,
    #[serde(default)]
    pub settings: Option<Value>,
    #[serde(default)]
    pub versions: Vec<Version>,
    #[serde(default)]
    pub route_cache: serde_json::Map<String, Value>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ImportReport {
    pub project: Project,
    pub created: bool,
    pub settings_imported: bool,
    pub versions_imported: usize,
    pub routes_imported: usize,
}
