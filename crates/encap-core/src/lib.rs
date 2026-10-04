//! Platform-neutral EnCap domain model, project persistence, and audio parsing.

mod archive_copy;
mod audio_editing;
mod error;
mod file_ops;
mod model;
mod project;
mod source;
mod transcript;
mod waveform;

pub use archive_copy::{stage_archive_copy, ArchiveCopyMethod};
pub use audio_editing::{edit_audio, AudioEdits};
pub use error::{EncapError, Result};
pub use file_ops::replace_staged_file;
pub use model::*;
pub use project::{load_project, save_project, PROJECT_SCHEMA_VERSION};
pub use source::{discover_audio_files, inspect_files, inspect_folder, inspect_source};
pub use transcript::{render_srt, render_transcript_text};

pub use waveform::{waveform_preview, WaveformPreview};

/// Compiled dependency identity, checked against Cargo.lock at build time.
pub const CORE_VERSION: &str = env!("ENCAP_CORE_VERSION");
pub const CORE_REVISION: &str = env!("ENCAP_CORE_REVISION");
pub const CORE_SOURCE: &str = env!("ENCAP_CORE_SOURCE");
