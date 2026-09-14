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

// Shared diagnostic text can contain paths and tool stderr. Keep it in local logs.
impl From<avid_core::Error> for EncapError {
    fn from(error: avid_core::Error) -> Self {
        tracing::error!(code = error.code(), details = ?error, "shared Video operation failed");
        let message = match error {
            avid_core::Error::Cancelled => "Video operation was cancelled safely.",
            avid_core::Error::Timeout(_) => "The Video media tool timed out. Try again or check the selected media.",
            avid_core::Error::ToolUnavailable { .. } => "The Video media tools are unavailable or incompatible. Restore a matching FFmpeg and ffprobe pair.",
            avid_core::Error::InvalidInput(ref detail) if detail == "Required software encoder libx264 is unavailable" => "Software H.264 encoding is unavailable in the bundled FFmpeg build.",
            avid_core::Error::InvalidInput(ref detail) if detail == "Required software encoder libx265 is unavailable" => "Software HEVC encoding is unavailable in the bundled FFmpeg build.",
            avid_core::Error::InvalidInput(ref detail) if detail == "Hardware H264 requested, but no compatible encoder is advertised" => "Hardware H.264 encoding is unavailable on this system.",
            avid_core::Error::InvalidInput(ref detail) if detail == "Hardware Hevc requested, but no compatible encoder is advertised" => "Hardware HEVC encoding is unavailable on this system.",
            avid_core::Error::InvalidInput(_) => "Check the Video selection, media, dimensions, frame rate, bitrate, and output destination. The output must be separate from project and source files.",
            avid_core::Error::Fallback { .. } => "Automatic hardware encoding failed and software fallback also failed. See local diagnostics for both attempts.",
            avid_core::Error::Io { .. } => "Video could not access a required file. Check file permissions and the output destination.",
            _ => "The Video media tool could not complete the operation. Check the selected media and local diagnostics.",
        };
        Self::Message(message.into())
    }
}
