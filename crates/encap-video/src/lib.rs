//! EnCAP project and artwork workflow adapter over the canonical Video renderer.
//! Operations block; callers must run them on application workers and join them
//! before replacing runtime tools. Every operation receives its own cancellation token.

pub use avid_core::{
    CancellationToken, Capabilities as VideoCapabilities,
    EncoderCapability as VideoEncoderCapability, Preset as VideoPreset, RenderMode, PRESETS,
};
use avid_core::{Clip, EventSink, Input, PreviewRequest, RenderRequest, Renderer, Timeline};
use encap_core::{Chapter, EncapError, ProjectDocument, Result};
use encap_ffmpeg::MediaTools;
use std::{
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        Mutex, OnceLock,
    },
    time::SystemTime,
};

mod artwork;
mod lifecycle;

/// A reusable session: clones share Core's bounded artwork/duration caches.
/// Core owns probing, composition graphs, subprocesses, and atomic publication.
#[derive(Clone, Debug)]
pub struct VideoRenderer {
    renderer: Renderer,
}

impl VideoRenderer {
    /// Construct with a validated Core tool pair, including injected test tools.
    pub fn new(renderer: Renderer) -> Self {
        Self { renderer }
    }

    /// Authenticate/discover the bundled runtime before reusing a matching session.
    /// Discovery is repeated so caching never bypasses runtime integrity checks.
    pub fn discover(cancellation: &CancellationToken) -> Result<Self> {
        let _operation = lifecycle::OperationGuard::acquire(None, cancellation)?;
        let tools = MediaTools::discover_with_cancellation(cancellation)?.into_core();
        let fingerprint = ToolFingerprint::new(&tools);
        static SESSION: OnceLock<Mutex<Option<(ToolFingerprint, VideoRenderer)>>> = OnceLock::new();
        let mut session = SESSION
            .get_or_init(|| Mutex::new(None))
            .lock()
            .map_err(|_| {
                EncapError::Message("Video renderer session could not be accessed.".into())
            })?;
        if let Some((cached, renderer)) = session.as_ref() {
            if cached == &fingerprint {
                return Ok(renderer.clone());
            }
        }
        let renderer = Self::new(Renderer::new(tools));
        *session = Some((fingerprint, renderer.clone()));
        Ok(renderer)
    }

    pub fn capabilities(&self, cancellation: &CancellationToken) -> Result<VideoCapabilities> {
        let _operation = lifecycle::OperationGuard::acquire(None, cancellation)?;
        self.renderer
            .capabilities(cancellation)
            .map_err(EncapError::from)
    }

    pub fn inspect_image(
        &self,
        image: &Path,
        cancellation: &CancellationToken,
    ) -> Result<(u32, u32)> {
        let _operation = lifecycle::OperationGuard::acquire(None, cancellation)?;
        self.renderer
            .inspect_image(image, cancellation)
            .map_err(EncapError::from)
    }

    /// Compose the main artwork or one chapter's artwork (with main fallback)
    /// using the project's exact EnCAP composition and flip settings.
    pub fn preview(
        &self,
        project: &ProjectDocument,
        destination: &Path,
        chapter_id: Option<&str>,
        cancellation: &CancellationToken,
    ) -> Result<PathBuf> {
        self.preview_with_events(project, destination, chapter_id, cancellation, &Diagnostics)
    }

    pub fn preview_with_events(
        &self,
        project: &ProjectDocument,
        destination: &Path,
        chapter_id: Option<&str>,
        cancellation: &CancellationToken,
        events: &dyn EventSink,
    ) -> Result<PathBuf> {
        project.validate()?;
        let main = main_artwork(project)?;
        let image = match chapter_id {
            Some(id) => {
                let available = project
                    .chapters
                    .iter()
                    .map(|chapter| chapter.id.as_str())
                    .collect::<Vec<_>>();
                let selected = avid_core::select_clip_indices(&available, &[id.to_owned()], true)
                    .map_err(EncapError::from)?;
                project.chapters[selected[0]]
                    .image_path
                    .as_deref()
                    .unwrap_or(main)
            }
            None => main,
        };
        let request = PreviewRequest {
            image: image.to_path_buf(),
            output: destination.to_path_buf(),
            settings: project
                .video
                .export_settings
                .render_settings()
                .map_err(EncapError::from)?,
            protected_paths: protected_paths(project),
        };
        let _operation = lifecycle::OperationGuard::acquire(Some(destination), cancellation)?;
        // Keep the existing rule even when this chapter supplies an override.
        self.renderer
            .inspect_image(main, cancellation)
            .map_err(EncapError::from)?;
        let events = CompletionEvents::new(events);
        self.renderer
            .preview(&request, cancellation, &events)
            .map_err(EncapError::from)?;
        events.require_complete()?;
        Ok(destination.to_path_buf())
    }

    /// Use cached frames for confidently static artwork within a conservative
    /// cache budget. Unknown/animated media and large timelines retain PerFrame.
    pub fn export(
        &self,
        project: &ProjectDocument,
        destination: &Path,
        cancellation: &CancellationToken,
    ) -> Result<PathBuf> {
        self.export_with_events(project, destination, None, cancellation, &Diagnostics)
    }

    /// Explicit comparison override; Simple intentionally freezes artwork animation.
    pub fn export_with_mode(
        &self,
        project: &ProjectDocument,
        destination: &Path,
        mode: RenderMode,
        cancellation: &CancellationToken,
    ) -> Result<PathBuf> {
        self.export_with_events(project, destination, Some(mode), cancellation, &Diagnostics)
    }

    /// An optional execution-only mode does not change saved Video project state.
    pub fn export_with_events(
        &self,
        project: &ProjectDocument,
        destination: &Path,
        mode: Option<RenderMode>,
        cancellation: &CancellationToken,
        events: &dyn EventSink,
    ) -> Result<PathBuf> {
        let request = render_request(project, destination)?;
        let _operation = lifecycle::OperationGuard::acquire(Some(destination), cancellation)?;
        self.renderer
            .inspect_image(main_artwork(project)?, cancellation)
            .map_err(EncapError::from)?;
        let mode = match mode {
            Some(mode) => mode,
            None => automatic_mode(&request, cancellation)?,
        };
        tracing::debug!(?mode, "Video frame generation policy");
        let events = CompletionEvents::new(events);
        self.renderer
            .render_with_mode(&request, mode, cancellation, &events)
            .map_err(EncapError::from)?;
        events.require_complete()?;
        // Preserve the caller's spelling in the engine JSON response.
        Ok(destination.to_path_buf())
    }
}

#[derive(PartialEq)]
struct ToolFingerprint(Vec<(PathBuf, Option<(u64, SystemTime)>)>);
impl ToolFingerprint {
    fn new(tools: &avid_core::MediaTools) -> Self {
        Self(
            [tools.ffmpeg(), tools.ffprobe()]
                .into_iter()
                .map(|path| {
                    let fingerprint = std::fs::metadata(path).ok().and_then(|metadata| {
                        metadata
                            .modified()
                            .ok()
                            .map(|modified| (metadata.len(), modified))
                    });
                    (path.to_path_buf(), fingerprint)
                })
                .collect(),
        )
    }
}

pub fn capabilities(cancellation: &CancellationToken) -> Result<VideoCapabilities> {
    VideoRenderer::discover(cancellation)?.capabilities(cancellation)
}

pub fn inspect_image(image: &Path, cancellation: &CancellationToken) -> Result<(u32, u32)> {
    VideoRenderer::discover(cancellation)?.inspect_image(image, cancellation)
}

pub fn preview(
    project: &ProjectDocument,
    destination: &Path,
    chapter_id: Option<&str>,
    cancellation: &CancellationToken,
) -> Result<PathBuf> {
    project.validate()?;
    main_artwork(project)?;
    VideoRenderer::discover(cancellation)?.preview(project, destination, chapter_id, cancellation)
}

pub fn export(
    project: &ProjectDocument,
    destination: &Path,
    cancellation: &CancellationToken,
) -> Result<PathBuf> {
    render_request(project, destination)?;
    VideoRenderer::discover(cancellation)?.export(project, destination, cancellation)
}

pub fn export_with_mode(
    project: &ProjectDocument,
    destination: &Path,
    mode: RenderMode,
    cancellation: &CancellationToken,
) -> Result<PathBuf> {
    render_request(project, destination)?;
    VideoRenderer::discover(cancellation)?.export_with_mode(
        project,
        destination,
        mode,
        cancellation,
    )
}

fn automatic_mode(request: &RenderRequest, cancellation: &CancellationToken) -> Result<RenderMode> {
    let images = match &request.input {
        Input::Timeline(timeline) => timeline
            .clips()
            .iter()
            .map(|clip| clip.image.as_path())
            .collect::<Vec<_>>(),
        Input::Single { image, .. } => vec![image.as_path()],
    };
    // Core caches one completed yuv420p frame PER CLIP, including repeated
    // artwork. Budget with four bytes/pixel to leave room for alignment and
    // filter bookkeeping; this is a policy bound, not a total RSS guarantee.
    const CACHED_FRAME_BUDGET: u64 = 256 * 1024 * 1024;
    let bytes = u64::from(request.settings.width) * u64::from(request.settings.height) * 4;
    if bytes.saturating_mul(images.len() as u64) > CACHED_FRAME_BUDGET {
        return Ok(RenderMode::PerFrame);
    }
    let mut checked = std::collections::HashSet::new();
    for image in images {
        if checked.insert(image) && !artwork::is_static(image, cancellation)? {
            return Ok(RenderMode::PerFrame);
        }
    }
    Ok(RenderMode::Simple)
}

fn protected_paths(project: &ProjectDocument) -> Vec<PathBuf> {
    project
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
        .collect()
}

// Keep focused legacy adapter tests on the original comparison path.
#[cfg(test)]
fn export_with_renderer(
    project: &ProjectDocument,
    request: &RenderRequest,
    renderer: &Renderer,
    cancellation: &CancellationToken,
) -> Result<()> {
    let _operation = lifecycle::OperationGuard::acquire(Some(&request.output), cancellation)?;
    renderer
        .inspect_image(main_artwork(project)?, cancellation)
        .map_err(EncapError::from)?;
    let events = CompletionEvents::new(&Diagnostics);
    renderer
        .render_with_mode(request, RenderMode::PerFrame, cancellation, &events)
        .map_err(EncapError::from)?;
    events.require_complete()
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
    let protected_paths = protected_paths(project);
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

struct CompletionEvents<'a> {
    events: &'a dyn EventSink,
    complete: AtomicBool,
}
impl<'a> CompletionEvents<'a> {
    fn new(events: &'a dyn EventSink) -> Self {
        Self {
            events,
            complete: AtomicBool::new(false),
        }
    }
    fn require_complete(&self) -> Result<()> {
        if self.complete.load(Ordering::Acquire) {
            Ok(())
        } else {
            Err(EncapError::Message(
                "Video did not confirm output publication.".into(),
            ))
        }
    }
}
impl EventSink for CompletionEvents<'_> {
    fn stage(&self, stage: avid_core::Stage) {
        if stage == avid_core::Stage::Complete {
            self.complete.store(true, Ordering::Release);
        }
        self.events.stage(stage);
    }
    fn progress(&self, progress: avid_core::Progress) {
        self.events.progress(progress);
    }
    fn diagnostic(&self, line: &str) {
        self.events.diagnostic(line);
    }
}

struct Diagnostics;
impl EventSink for Diagnostics {
    fn diagnostic(&self, line: &str) {
        tracing::debug!(diagnostic = line, "Video media tool");
    }
    fn stage(&self, stage: avid_core::Stage) {
        tracing::debug!(stage = stage.as_str(), "Video stage");
    }
    fn progress(&self, progress: avid_core::Progress) {
        tracing::debug!(
            elapsed_seconds = progress.elapsed_seconds,
            duration_seconds = progress.duration_seconds,
            fraction = progress.fraction,
            eta_seconds = progress.eta_seconds,
            "Video progress"
        );
    }
}

#[cfg(test)]
mod tests;
