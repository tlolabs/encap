//! Project-path and JSON adaptation for Core's in-process artwork optimizer.

use avid_core::{
    CancellationToken, ImageOptimizationOptions, ImageOptimizationRequest, OptimizedImageFormat,
};
use encap_core::{EncapError, ProjectDocument, Result};
use serde_json::{json, Value};
use std::path::Path;

pub fn optimize(
    project: &ProjectDocument,
    payload: &Path,
    image: &Path,
    output: &Path,
    cancellation: &CancellationToken,
) -> Result<Value> {
    let protected_paths = project
        .audio_sources
        .iter()
        .map(|source| source.source_path.clone())
        .chain(project.metadata.artwork_path.iter().cloned())
        .chain(
            project
                .chapters
                .iter()
                .filter_map(|chapter| chapter.image_path.clone()),
        )
        .chain(project.project_path.iter().cloned())
        .chain(std::iter::once(payload.to_path_buf()))
        .collect();
    let result = avid_core::optimize_image(
        &ImageOptimizationRequest {
            input: image.to_path_buf(),
            output: output.to_path_buf(),
            options: ImageOptimizationOptions::default(),
            protected_paths,
        },
        cancellation,
    )
    .map_err(artwork_error)?;
    Ok(json!({
        "path": output,
        "format": match result.format {
            OptimizedImageFormat::Jpeg => "jpeg",
            OptimizedImageFormat::Png => "png",
        },
        "input_bytes": result.input_bytes,
        "output_bytes": result.output_bytes,
        "bytes_saved": result.bytes_saved,
        "optimized": result.optimized,
    }))
}

fn artwork_error(error: avid_core::Error) -> EncapError {
    tracing::error!(code = error.code(), details = ?error, "shared artwork optimization failed");
    let message = match error {
        avid_core::Error::Cancelled => "Artwork optimization was cancelled safely.",
        avid_core::Error::InvalidInput(_) => "Artwork optimization requires a valid, static, opaque JPEG or PNG and a separate output file of the same format. The output must not replace project or source files.",
        avid_core::Error::Io { .. } => "Artwork optimization could not access a required file. Check file permissions and the output destination.",
        _ => "Artwork optimization could not complete. Check the image and local diagnostics.",
    };
    EncapError::Message(message.into())
}
