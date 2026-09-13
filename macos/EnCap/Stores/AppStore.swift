import AVFoundation
import Combine
import Foundation
#if SWIFT_PACKAGE
import SparkleBridge
#endif
import SwiftUI
import UniformTypeIdentifiers

@MainActor
final class AppStore: ObservableObject {
    enum FileImportKind {
        case audioFolder
        case project
        case artwork
    }

    @Published var project: ProjectDocument?
    @Published private(set) var workspace = WorkspaceMode.audio
    @Published var providers: [TranscriptionProvider] = []
    @Published var transcriptionModels: [TranscriptionModelInfo] = []
    @Published var selectedProviderID = "apple-local"
    @Published var videoPresets: [VideoPreset] = []
    @Published var videoCapabilities = VideoCapabilities()
    @Published var videoCurrentTime = 0.0
    @Published var isVideoPlaying = false
    @Published var transcriptSearch = ""
    @Published var transcriptShowsSpeakers = true
    @Published var isModelManagerPresented = false
    @Published var isWorking = false
    @Published var status = "Import an audio folder to begin."
    @Published var errorMessage: String?
    @Published var fileImportKind: FileImportKind?
    @Published var isFileImporterPresented = false
    @Published private(set) var isPlaying = false

    private let engine = EngineClient()
    private var player: AVPlayer?
    private var playbackEndObserver: NSObjectProtocol?
    private var videoTimeObserver: Any?
    private var videoPlaybackIndex: Int?
    private var savedProject: ProjectDocument?
    private var cancellationRequested = false
    private var recoveryObservation: AnyCancellable?

    var hasUnsavedChanges: Bool { project != nil && project != savedProject }

    func confirmDiscardChanges() -> Bool {
        guard !isWorking else {
            errorMessage = "Wait for the current operation to finish before closing or replacing the project."
            return false
        }
        guard hasUnsavedChanges else { return true }
        let alert = NSAlert()
        alert.messageText = "Save changes to this EnCap project?"
        alert.informativeText = "Your changes will be lost if you close or replace the project without saving."
        alert.addButton(withTitle: "Save Project")
        alert.addButton(withTitle: "Cancel")
        alert.addButton(withTitle: "Don't Save")
        switch alert.runModal() {
        case .alertFirstButtonReturn:
            presentSavePanel()
            return false
        case .alertThirdButtonReturn:
            return true
        default:
            return false
        }
    }

    func cleanupSession() {
        stopPlayback()
        engine.cleanupSession()
    }

    private func replaceProject(_ next: ProjectDocument, saved: Bool) {
        stopPlayback()
        if let project { engine.cleanup(project: project) }
        var normalized = next
        normalizeVideoSelection(&normalized)
        project = normalized
        workspace = normalized.activeMode
        savedProject = saved ? normalized : nil
    }

    init() {
        _ = EnCapStartUpdater()
        recoveryObservation = $project
            .dropFirst()
            .debounce(for: .seconds(1), scheduler: RunLoop.main)
            .sink { [weak self] project in
                guard let self, !self.isWorking else { return }
                Task { @MainActor in
                    if let project, project != self.savedProject {
                        try? await self.engine.saveRecovery(project)
                    } else {
                        try? await self.engine.clearRecovery()
                    }
                }
            }
        Task { await restoreRecoveryIfAvailable() }
    }

    private func restoreRecoveryIfAvailable() async {
        do {
            guard project == nil, let recovered = try await engine.loadRecovery() else { return }
            replaceProject(recovered, saved: false)
            status = "Recovered unsaved work from the previous session."
        } catch {
            errorMessage = "Unsaved work could not be recovered: \(error.localizedDescription)"
        }
    }

    func prepareToTerminate() async {
        try? await engine.clearRecovery()
        cleanupSession()
    }

    var isProjectLoaded: Bool { project != nil }

    var selectedVideoChapters: [Chapter] {
        guard let project else { return [] }
        let ids = project.video.exportSettings.selectedChapterIds
        if ids.isEmpty && !project.video.exportSettings.selectionInitialized { return project.chapters }
        return ids.compactMap { id in project.chapters.first { $0.id == id } }
    }

    var selectedVideoDuration: Double {
        selectedVideoChapters.reduce(0) { $0 + $1.durationSeconds }
    }

    func switchWorkspace(to target: WorkspaceMode) {
        guard target != workspace, !isWorking else { return }
        guard var project else {
            workspace = target
            return
        }
        if !hasUnsavedChanges && project.projectPath == nil {
            project.activeMode = target
            self.project = project
            workspace = target
            savedProject = project.projectPath == nil ? nil : project
            return
        }
        if let path = project.projectPath {
            project.activeMode = target
            perform("Saving before switching to \(target.rawValue)…") {
                let url = try await self.engine.save(project, to: URL(fileURLWithPath: path))
                project.projectPath = url.path
                self.project = project
                self.savedProject = project
                self.workspace = target
                self.status = "Saved project and opened \(target.rawValue)."
            }
            return
        }
        let alert = NSAlert()
        alert.messageText = "Save this project before switching modes?"
        alert.informativeText = "You can continue without saving; EnCap will keep the complete project in temporary recovery storage until you close the app."
        alert.addButton(withTitle: "Save Project")
        alert.addButton(withTitle: "Continue Without Saving")
        alert.addButton(withTitle: "Cancel")
        switch alert.runModal() {
        case .alertFirstButtonReturn:
            presentSavePanel(switchingTo: target)
        case .alertSecondButtonReturn:
            completeUnsavedWorkspaceSwitch(to: target)
        default:
            break
        }
    }

    private func completeUnsavedWorkspaceSwitch(to target: WorkspaceMode) {
        project?.activeMode = target
        workspace = target
        status = "Opened \(target.rawValue) without saving. Crash recovery remains active."
    }

    func presentFileImporter(_ kind: FileImportKind) {
        guard !isWorking else { return }
        fileImportKind = kind
        isFileImporterPresented = true
    }

    func completeFileImport(_ result: Result<[URL], Error>) {
        defer { fileImportKind = nil }
        switch result {
        case .success(let urls):
            guard let url = urls.first, let fileImportKind else { return }
            switch fileImportKind {
            case .audioFolder:
                importFolder(url)
            case .project:
                openProject(url)
            case .artwork:
                chooseArtwork(url)
            }
        case .failure(let error):
            let cocoaError = error as NSError
            guard cocoaError.domain != NSCocoaErrorDomain
                    || cocoaError.code != NSUserCancelledError else { return }
            errorMessage = error.localizedDescription
        }
    }

    func importFolder(_ url: URL) {
        guard confirmDiscardChanges() else { return }
        perform("Reading \(url.lastPathComponent)…") {
            let project = try await self.engine.inspect(folder: url)
            self.replaceProject(project, saved: false)
            self.status = "Imported \(project.audioSources.count) audio files."
        }
    }

    func openProject(_ url: URL) {
        guard confirmDiscardChanges() else { return }
        perform("Opening \(url.lastPathComponent)…") {
            let opened = try await self.engine.open(project: url)
            self.replaceProject(opened, saved: true)
            self.status = "Opened \(url.lastPathComponent)."
        }
    }

    func presentSavePanel(exportAudio: Bool = false, switchingTo: WorkspaceMode? = nil) {
        guard let project, !isWorking else { return }
        let panel = NSSavePanel()
        panel.allowedContentTypes = exportAudio
            ? [project.exportSettings.fileExtension == "m4a" ? .mpeg4Audio : .mp3]
            : [.encapProject]
        panel.nameFieldStringValue = "\(project.outputBaseName).\(exportAudio ? project.exportSettings.fileExtension : "encap")"
        panel.canCreateDirectories = true
        panel.title = exportAudio ? "Export Audio" : "Save Project"
        let completion: (NSApplication.ModalResponse) -> Void = { [weak self] response in
            guard response == .OK, let url = panel.url else { return }
            if exportAudio { self?.exportAudio(to: url) }
            else { self?.saveProject(to: url, switchingTo: switchingTo) }
        }
        if let window = NSApp.keyWindow {
            panel.beginSheetModal(for: window, completionHandler: completion)
        } else {
            panel.begin(completionHandler: completion)
        }
    }

    func saveProject(to url: URL, switchingTo: WorkspaceMode? = nil) {
        guard var project else { return }
        if let switchingTo { project.activeMode = switchingTo }
        perform("Saving project…") {
            let savedURL = try await self.engine.save(project, to: url)
            self.project?.projectPath = savedURL.path
            var saved = project
            saved.projectPath = savedURL.path
            self.savedProject = saved
            if let switchingTo {
                self.project?.activeMode = switchingTo
                self.workspace = switchingTo
            }
            self.status = "Saved \(savedURL.lastPathComponent)."
        }
    }

    func exportAudio(to url: URL) {
        guard let project else { return }
        perform("Exporting audio…") {
            let output = try await self.engine.export(project, to: url)
            self.status = "Exported \(output.lastPathComponent)."
        }
    }

    func loadVideoSupport() {
        Task {
            do {
                async let presets = engine.videoPresets()
                async let capabilities = engine.videoCapabilities()
                videoPresets = try await presets
                videoCapabilities = try await capabilities
            } catch {
                errorMessage = "Video support could not be loaded: \(error.localizedDescription)"
            }
        }
    }

    func presentVideoSavePanel() {
        guard let project, !selectedVideoChapters.isEmpty, !isWorking else { return }
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.mpeg4Movie]
        panel.nameFieldStringValue = "\(project.outputBaseName).mp4"
        panel.canCreateDirectories = true
        panel.title = "Export Video"
        let completion: (NSApplication.ModalResponse) -> Void = { [weak self] response in
            guard response == .OK, let url = panel.url else { return }
            self?.exportVideo(to: url)
        }
        if let window = NSApp.keyWindow {
            panel.beginSheetModal(for: window, completionHandler: completion)
        } else {
            panel.begin(completionHandler: completion)
        }
    }

    private func exportVideo(to url: URL) {
        guard let project else { return }
        perform("Exporting MP4 video…") {
            let output = try await self.engine.exportVideo(project, to: url)
            self.status = "Exported \(output.lastPathComponent)."
        }
    }

    func loadProviders() {
        Task {
            do {
                providers = try await engine.providers()
                if !providers.contains(where: { $0.id == selectedProviderID }) {
                    selectedProviderID = providers.first?.id ?? ""
                }
            } catch {
                providers = []
                errorMessage = "Could not load transcription engines: \(error.localizedDescription)"
            }
        }
    }

    func presentModelManager() {
        isModelManagerPresented = true
        Task { await refreshModels() }
    }

    func installModel(_ model: TranscriptionModelInfo) {
        perform("Downloading \(model.name)…") {
            _ = try await self.engine.installModel(id: model.id)
            await self.refreshModels()
            self.loadProviders()
            self.selectedProviderID = model.id
            self.status = "Installed \(model.name)."
        }
    }

    func removeModel(_ model: TranscriptionModelInfo) {
        perform("Removing \(model.name)…") {
            _ = try await self.engine.removeModel(id: model.id)
            await self.refreshModels()
            self.loadProviders()
            self.status = "Removed \(model.name)."
        }
    }

    private func refreshModels() async {
        do {
            transcriptionModels = try await engine.models()
        } catch {
            errorMessage = "Could not load the model catalog: \(error.localizedDescription)"
        }
    }

    func transcribe() {
        guard let project, !selectedProviderID.isEmpty else { return }
        perform("Transcribing locally…") {
            let segments = try await self.engine.transcribe(
                project,
                providerID: self.selectedProviderID,
                wordTimestamps: project.transcriptSettings.includeWordTimestamps
            )
            self.project?.transcriptSegments = segments
            self.workspace = .transcript
            self.project?.activeMode = .transcript
            self.status = "Transcription complete."
        }
    }

    func presentTranscriptSavePanel(format: String) {
        guard let project, !project.transcriptSegments.isEmpty, !isWorking else { return }
        let panel = NSSavePanel()
        let fileExtension = format == "srt" ? "srt" : "txt"
        panel.allowedContentTypes = [UTType(filenameExtension: fileExtension) ?? .plainText]
        panel.nameFieldStringValue = "\(project.outputBaseName).\(fileExtension)"
        panel.canCreateDirectories = true
        panel.title = format == "srt" ? "Export SRT Captions" : "Export Transcript"
        let completion: (NSApplication.ModalResponse) -> Void = { [weak self] response in
            guard response == .OK, let url = panel.url else { return }
            self?.exportTranscript(to: url, format: format)
        }
        if let window = NSApp.keyWindow {
            panel.beginSheetModal(for: window, completionHandler: completion)
        } else {
            panel.begin(completionHandler: completion)
        }
    }

    private func exportTranscript(to url: URL, format: String) {
        guard let project else { return }
        perform("Exporting transcript…") {
            let output = try await self.engine.exportTranscript(project, to: url, format: format)
            self.status = "Exported \(output.lastPathComponent)."
        }
    }

    func chooseArtwork(_ url: URL) {
        project?.metadata.artworkPath = url.path
        status = "Selected \(url.lastPathComponent) as episode artwork."
    }

    func chooseChapterArtwork(for chapterID: String) {
        guard !isWorking else { return }
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.image]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.title = "Choose Chapter Artwork"
        let completion: (NSApplication.ModalResponse) -> Void = { [weak self] response in
            guard response == .OK, let url = panel.url,
                  let index = self?.project?.chapters.firstIndex(where: { $0.id == chapterID }) else { return }
            self?.project?.chapters[index].imagePath = url.path
            self?.status = "Selected \(url.lastPathComponent) as chapter artwork."
        }
        if let window = NSApp.keyWindow {
            panel.beginSheetModal(for: window, completionHandler: completion)
        } else {
            panel.begin(completionHandler: completion)
        }
    }

    func addChapter() {
        guard var project else { return }
        let start = project.chapters.last.map { $0.startTimeSeconds + $0.durationSeconds } ?? 0
        let number = project.chapters.count + 1
        project.chapters.append(
            Chapter(
                startTimeSeconds: start,
                durationSeconds: 5,
                chapterNumber: number,
                title: "Chapter \(number)"
            )
        )
        self.project = project
    }

    func removeChapters(at offsets: IndexSet) {
        project?.chapters.remove(atOffsets: offsets)
        renumberChapters()
    }

    func moveChapters(from offsets: IndexSet, to destination: Int) {
        project?.chapters.move(fromOffsets: offsets, toOffset: destination)
        renumberChapters()
    }

    func play(source: AudioSource, at offset: Double = 0) {
        stopPlayback()
        let nextPlayer = AVPlayer(url: URL(fileURLWithPath: source.sourcePath))
        player = nextPlayer
        nextPlayer.seek(to: CMTime(seconds: max(0, offset), preferredTimescale: 600),
                        toleranceBefore: .zero, toleranceAfter: .zero)
        nextPlayer.play()
        playbackEndObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemDidPlayToEndTime,
            object: nextPlayer.currentItem,
            queue: .main
        ) { [weak self, weak nextPlayer] _ in
            Task { @MainActor in
                guard let self, self.player === nextPlayer else { return }
                self.player = nil
                if let observer = self.playbackEndObserver {
                    NotificationCenter.default.removeObserver(observer)
                }
                self.playbackEndObserver = nil
                self.isPlaying = false
                self.status = "Playback finished."
            }
        }
        isPlaying = true
        status = "Playing \(source.displayName)."
    }

    func stopPlayback() {
        player?.pause()
        if let videoTimeObserver, let player {
            player.removeTimeObserver(videoTimeObserver)
        }
        videoTimeObserver = nil
        if let playbackEndObserver {
            NotificationCenter.default.removeObserver(playbackEndObserver)
            self.playbackEndObserver = nil
        }
        player = nil
        isPlaying = false
        isVideoPlaying = false
        videoPlaybackIndex = nil
    }

    func toggleVideoPlayback() {
        if isVideoPlaying {
            player?.pause()
            isVideoPlaying = false
            status = "Video preview paused."
        } else if let player {
            player.play()
            isVideoPlaying = true
            status = "Playing Video preview."
        } else {
            seekVideo(to: videoCurrentTime, autoplay: true)
        }
    }

    func seekVideo(to requestedTime: Double, autoplay: Bool? = nil) {
        let chapters = selectedVideoChapters
        guard !chapters.isEmpty, let project else { return }
        let target = min(max(0, requestedTime), selectedVideoDuration)
        var cumulative = 0.0
        var index = chapters.count - 1
        for candidate in chapters.indices {
            if target < cumulative + chapters[candidate].durationSeconds {
                index = candidate
                break
            }
            cumulative += chapters[candidate].durationSeconds
        }
        let shouldPlay = autoplay ?? isVideoPlaying
        stopPlayback()
        let chapter = chapters[index]
        guard let source = source(for: chapter, in: project) else { return }
        let nextPlayer = AVPlayer(url: URL(fileURLWithPath: source.sourcePath))
        player = nextPlayer
        videoPlaybackIndex = index
        videoCurrentTime = target
        nextPlayer.seek(to: CMTime(seconds: max(0, target - cumulative), preferredTimescale: 600), toleranceBefore: .zero, toleranceAfter: .zero)
        videoTimeObserver = nextPlayer.addPeriodicTimeObserver(
            forInterval: CMTime(seconds: 0.05, preferredTimescale: 600),
            queue: .main
        ) { [weak self, weak nextPlayer] time in
            Task { @MainActor in
                guard let self, self.player === nextPlayer, self.videoPlaybackIndex == index else { return }
                let elapsed = min(time.seconds, chapter.durationSeconds)
                self.videoCurrentTime = cumulative + max(0, elapsed)
                if elapsed >= chapter.durationSeconds - 0.04 {
                    self.playVideoChapter(index + 1)
                }
            }
        }
        if shouldPlay {
            nextPlayer.play()
            isVideoPlaying = true
        }
        isPlaying = true
    }

    func previousVideoChapter() {
        guard let current = currentVideoChapterIndex else { return }
        jumpToVideoChapter(max(0, current - 1), autoplay: isVideoPlaying)
    }

    func nextVideoChapter() {
        guard let current = currentVideoChapterIndex else { return }
        jumpToVideoChapter(min(selectedVideoChapters.count - 1, current + 1), autoplay: isVideoPlaying)
    }

    func jumpToVideoChapter(_ index: Int, autoplay: Bool = false) {
        guard selectedVideoChapters.indices.contains(index) else { return }
        let start = selectedVideoChapters.prefix(index).reduce(0) { $0 + $1.durationSeconds }
        seekVideo(to: start, autoplay: autoplay)
    }

    var currentVideoChapterIndex: Int? {
        let chapters = selectedVideoChapters
        guard !chapters.isEmpty else { return nil }
        var start = 0.0
        for index in chapters.indices {
            if videoCurrentTime < start + chapters[index].durationSeconds { return index }
            start += chapters[index].durationSeconds
        }
        return chapters.indices.last
    }

    func setVideoChapter(_ chapter: Chapter, selected: Bool) {
        guard var project else { return }
        var ids = project.video.exportSettings.selectedChapterIds
        if ids.isEmpty { ids = project.chapters.map(\.id) }
        if selected {
            if !ids.contains(chapter.id) { ids.append(chapter.id) }
        } else {
            ids.removeAll { $0 == chapter.id }
        }
        project.video.exportSettings.selectedChapterIds = ids
        project.video.exportSettings.selectionInitialized = true
        self.project = project
        stopPlayback()
        videoCurrentTime = 0
    }

    func selectAllVideoChapters(_ selected: Bool) {
        project?.video.exportSettings.selectedChapterIds = selected ? (project?.chapters.map(\.id) ?? []) : []
        project?.video.exportSettings.selectionInitialized = true
        stopPlayback()
        videoCurrentTime = 0
    }

    func moveVideoChapters(from offsets: IndexSet, to destination: Int) {
        guard var project else { return }
        var ids = selectedVideoChapters.map(\.id)
        ids.move(fromOffsets: offsets, toOffset: destination)
        project.video.exportSettings.selectedChapterIds = ids
        project.video.exportSettings.selectionInitialized = true
        self.project = project
        stopPlayback()
        videoCurrentTime = 0
    }

    func moveVideoChapter(id: String, direction: Int) {
        guard var project else { return }
        var ids = selectedVideoChapters.map(\.id)
        guard let index = ids.firstIndex(of: id) else { return }
        let target = index + direction
        guard ids.indices.contains(target) else { return }
        ids.swapAt(index, target)
        project.video.exportSettings.selectedChapterIds = ids
        project.video.exportSettings.selectionInitialized = true
        self.project = project
    }

    func effectiveArtwork(for chapter: Chapter) -> URL? {
        guard let path = chapter.imagePath ?? project?.metadata.artworkPath else { return nil }
        return URL(fileURLWithPath: path)
    }

    func cancelCurrentOperation() {
        guard isWorking else { return }
        cancellationRequested = true
        status = "Cancelling safely…"
        engine.cancelCurrentOperation()
    }

    func checkForUpdates() {
        if !EnCapCheckForUpdates() {
            errorMessage = "The update service is unavailable in this build."
        }
    }

    private func renumberChapters() {
        guard var project else { return }
        var start = 0.0
        for index in project.chapters.indices {
            project.chapters[index].chapterNumber = index + 1
            project.chapters[index].startTimeSeconds = start
            start += project.chapters[index].durationSeconds
        }
        self.project = project
    }

    private func normalizeVideoSelection(_ project: inout ProjectDocument) {
        let known = Set(project.chapters.map(\.id))
        var ids = project.video.exportSettings.selectedChapterIds.filter { known.contains($0) }
        if ids.isEmpty && !project.video.exportSettings.selectionInitialized {
            ids = project.chapters.map(\.id)
        }
        project.video.exportSettings.selectedChapterIds = ids
        project.video.exportSettings.selectionInitialized = true
    }

    private func source(for chapter: Chapter, in project: ProjectDocument) -> AudioSource? {
        guard chapter.chapterNumber > 0 else { return nil }
        let index = chapter.chapterNumber - 1
        return project.audioSources.indices.contains(index) ? project.audioSources[index] : nil
    }

    private func playVideoChapter(_ index: Int) {
        guard selectedVideoChapters.indices.contains(index) else {
            stopPlayback()
            videoCurrentTime = selectedVideoDuration
            status = "Video preview finished."
            return
        }
        jumpToVideoChapter(index, autoplay: true)
    }

    private func perform(_ activity: String, operation: @escaping @MainActor () async throws -> Void) {
        guard !isWorking else { return }
        cancellationRequested = false
        isWorking = true
        status = activity
        Task {
            defer {
                isWorking = false
                // Re-arm debounced recovery if an edit and a long operation
                // began within the same one-second window.
                project = project
            }
            do {
                try await operation()
            } catch {
                if cancellationRequested {
                    status = "Operation cancelled."
                } else {
                    errorMessage = error.localizedDescription
                    status = "Operation failed."
                }
            }
        }
    }
}
