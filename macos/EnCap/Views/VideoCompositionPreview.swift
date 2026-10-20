import AppKit
import SwiftUI

struct VideoPreviewIdentity: Hashable {
    let chapterID: String
    let artwork: URL
    let size: Int?
    let modified: Date?
    let mainArtwork: URL?
    let mainSize: Int?
    let mainModified: Date?
    let projectIdentity: String?
    let settings: VideoSettings

    init(chapterID: String, artwork: URL, settings: VideoSettings,
         mainArtwork: URL? = nil, projectIdentity: String? = nil) {
        self.chapterID = chapterID
        self.artwork = artwork.standardizedFileURL
        // URL resource values are cached on the URL instance; stat the path so
        // replacing an artwork file also refreshes an already visible preview.
        let values = try? FileManager.default.attributesOfItem(atPath: self.artwork.path)
        size = (values?[.size] as? NSNumber)?.intValue
        modified = values?[.modificationDate] as? Date
        self.mainArtwork = mainArtwork?.standardizedFileURL
        let mainValues = self.mainArtwork.flatMap { try? FileManager.default.attributesOfItem(atPath: $0.path) }
        mainSize = (mainValues?[.size] as? NSNumber)?.intValue
        mainModified = mainValues?[.modificationDate] as? Date
        self.projectIdentity = projectIdentity
        self.settings = settings
    }
}

/// Displays the PNG composed by Core, using a separate process and cancellation
/// scope from audio playback and exports. The task identity excludes playhead time.
struct VideoCompositionPreview: View {
    let project: ProjectDocument
    let chapterID: String
    let artwork: URL
    @State private var image: NSImage?
    @State private var failure: String?

    private var identity: VideoPreviewIdentity {
        VideoPreviewIdentity(
            chapterID: chapterID, artwork: artwork, settings: project.video.exportSettings,
            mainArtwork: project.metadata.artworkPath.map { URL(fileURLWithPath: $0) },
            projectIdentity: "\(project.projectPath ?? "")|\(project.workingDir ?? "")|\(project.projectTitle)|\(project.schemaVersion)|\(project.video.schemaVersion)"
        )
    }

    var body: some View {
        Group {
            if let image {
                Image(nsImage: image).resizable().scaledToFit()
            } else if let failure {
                VStack(spacing: 8) {
                    Image(systemName: "exclamationmark.triangle")
                    Text("Preview unavailable").font(.headline)
                    Text(failure).font(.caption).multilineTextAlignment(.center)
                }
                .padding()
                .foregroundStyle(.white)
            } else {
                ProgressView("Composing preview…")
                    .tint(.white)
                    .foregroundStyle(.white)
            }
        }
        .task(id: identity) { await compose() }
    }

    @MainActor
    private func compose() async {
        image = nil
        failure = nil
        let engine = EngineClient()
        defer { engine.cleanupSession() }
        do {
            try Task.checkCancellation()
            try FileManager.default.createDirectory(
                at: engine.sessionDirectory, withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700]
            )
            let output = engine.sessionDirectory.appendingPathComponent("composition.png")
            let rendered = try await engine.previewVideo(project, chapterID: chapterID, to: output)
            try Task.checkCancellation()
            guard let composed = NSImage(data: try Data(contentsOf: rendered)) else { throw EngineError.invalidResponse }
            image = composed
        } catch {
            if !Task.isCancelled { failure = error.localizedDescription }
        }
    }
}
