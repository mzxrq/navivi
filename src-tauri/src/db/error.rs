use rusqlite::ErrorCode;
use serde::ser::SerializeStruct;
use serde::{Serialize, Serializer};

#[derive(Debug, thiserror::Error)]
pub enum DbError {
    #[error("{0} not found")]
    NotFound(String),
    #[error("{0}")]
    Conflict(String),
    #[error("{0}")]
    Invalid(String),
    #[error(transparent)]
    Sqlite(#[from] rusqlite::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}

pub type DbResult<T> = Result<T, DbError>;

impl DbError {
    pub fn code(&self) -> &'static str {
        match self {
            DbError::NotFound(_) => "not_found",
            DbError::Conflict(_) => "conflict",
            DbError::Invalid(_) | DbError::Json(_) => "invalid",
            DbError::Sqlite(e) if is_constraint(e) => "conflict",
            DbError::Sqlite(_) => "db",
        }
    }
}

pub fn is_constraint(e: &rusqlite::Error) -> bool {
    matches!(e, rusqlite::Error::SqliteFailure(f, _) if f.code == ErrorCode::ConstraintViolation)
}

// The frontend receives `{ code, message }` and branches on `code`.
impl Serialize for DbError {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let mut s = serializer.serialize_struct("DbError", 2)?;
        s.serialize_field("code", self.code())?;
        s.serialize_field("message", &self.to_string())?;
        s.end()
    }
}
