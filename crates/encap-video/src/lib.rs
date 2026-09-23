//! EnCAP project and artwork workflow adapter over the canonical Video renderer.

pub use avid_core::{
    CancellationToken, Capabilities as VideoCapabilities,
    EncoderCapability as VideoEncoderCapability, Preset as VideoPreset, PRESETS,
};
use avid_core::{Clip, EventSink, Input, RenderRequest, Renderer, Timeline};
use encap_core::{Chapter, EncapError, ProjectDocument, Result};
use encap_ffmpeg::MediaTools;
use std::path::{Path, PathBuf};

fn renderer(cancellation: &CancellationToken) -> Result<Renderer> {
    if cancellation.is_cancelled() {
        return Err(EncapError::from(avid_core::Error::Cancelled));
    }
    let host = MediaTools::discover_with_cancellation(cancellation)?;
    Ok(Renderer::new(host.into_core()))
}

pub fn capabilities(cancellation: &CancellationToken) -> Result<VideoCapabilities> {
    renderer(cancellation)?
        .capabilities(cancellation)
        .map_err(EncapError::from)
}

pub fn export(
    project: &ProjectDocument,
    destination: &Path,
    cancellation: &CancellationToken,
) -> Result<PathBuf> {
    let request = render_request(project, destination)?;
    let renderer = renderer(cancellation)?;
    export_with_renderer(project, &request, &renderer, cancellation)?;
    // Preserve the caller's path spelling in the engine's existing response.
    Ok(destination.to_path_buf())
}

fn export_with_renderer(
    project: &ProjectDocument,
    request: &RenderRequest,
    renderer: &Renderer,
    cancellation: &CancellationToken,
) -> Result<()> {
    // Audio's main-artwork workflow rule applies even when every clip overrides it.
    renderer
        .inspect_image(main_artwork(project)?, cancellation)
        .map_err(EncapError::from)?;
    renderer
        .render(request, cancellation, &Diagnostics)
        .map_err(EncapError::from)?;
    Ok(())
}

fn main_artwork(project: &ProjectDocument) -> Result<&Path> {
    project.metadata.artwork_path.as_deref().ok_or_else(|| {
        EncapError::Message("Add project artwork in Audio before using Video.".into())
    })
}

/// Map selected records only; chapter numbers refer to canonical source order.
fn render_request(project: &ProjectDocument, destination: &Path) -> Result<RenderRequest> {
    project.validate()?;
    main_artwork(project)?;
    let clips = selected_chapters(project)?
        .into_iter()
        .map(|chapter| {
            let source = chapter
                .chapter_number
                .checked_sub(1)
                .and_then(|number| project.audio_sources.get(number as usize))
                .ok_or_else(|| {
                    EncapError::Message(format!(
                        "Chapter {} has no source audio.",
                        chapter.chapter_number
                    ))
                })?;
            let image = chapter
                .image_path
                .as_ref()
                .or(project.metadata.artwork_path.as_ref())
                .ok_or_else(|| {
                    EncapError::Message("Add project artwork in Audio before using Video.".into())
                })?;
            Ok(Clip {
                id: chapter.id.clone(),
                duration_seconds: chapter.duration_seconds,
                audio: source.source_path.clone(),
                image: image.clone(),
            })
        })
        .collect::<Result<Vec<_>>>()?;
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
        .collect();
    Ok(RenderRequest {
        input: Input::Timeline(Timeline::new(clips).map_err(EncapError::from)?),
        output: destination.to_path_buf(),
        settings: project
            .video
            .export_settings
            .render_settings()
            .map_err(EncapError::from)?,
        protected_paths,
    })
}

pub fn selected_chapters(project: &ProjectDocument) -> Result<Vec<&Chapter>> {
    let chapter_ids = project
        .chapters
        .iter()
        .map(|chapter| chapter.id.as_str())
        .collect::<Vec<_>>();
    let settings = &project.video.export_settings;
    Ok(avid_core::select_clip_indices(
        &chapter_ids,
        &settings.selected_chapter_ids,
        settings.selection_initialized,
    )
    .map_err(EncapError::from)?
    .into_iter()
    .map(|index| &project.chapters[index])
    .collect())
}

struct Diagnostics;
impl EventSink for Diagnostics {
    fn diagnostic(&self, line: &str) {
        tracing::debug!(diagnostic = line, "Video media tool");
    }
    fn stage(&self, stage: avid_core::Stage) {
        tracing::debug!(stage = stage.as_str(), "Video stage");
    }
}

#[cfg(test)]
mod tests;
