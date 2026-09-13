use std::path::PathBuf;

#[derive(Debug, thiserror::Error)]
pub enum EncapError {
    #[error("{0}")]
    Message(String),
    #[error("The file could not be read: {path}: {source}")]
    Read {
        path: PathBuf,
        source: std::io::Error,
    },
    #[error("The file could not be written safely: {path}: {source}")]
    Write {
        path: PathBuf,
        source: std::io::Error,
    },
    #[error("The project archive is invalid: {0}")]
    Archive(#[from] zip::result::ZipError),
    #[error("The project manifest is invalid: {0}")]
    Json(#[from] serde_json::Error),
    #[error("Unsupported audio file: {0}")]
    UnsupportedAudio(String),
    #[error(
        "Unsupported project schema version {found}; this build supports version {supported}."
    )]
    UnsupportedSchema { found: u64, supported: u64 },
}

pub type Result<T> = std::result::Result<T, EncapError>;
