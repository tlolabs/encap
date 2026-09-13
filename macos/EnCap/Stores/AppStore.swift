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
    enum Workspace: String, CaseIterable, Identifiable {
        case process = "Process Audio"
        case transcribe = "Transcribe"
        var id: String { rawValue }
    }

    enum FileImportKind {
        case audioFolder
        case project
        case artwork
    }

    @Published var project: ProjectDocument?
    @Published var workspace = Workspace.process
    @Published var providers: [TranscriptionProvider] = []
    @Published var transcriptionModels: [TranscriptionModelInfo] = []
    @Published var selectedProviderID = "apple-local"
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
        alert.messageText = "Discard unsaved changes?"
        alert.informativeText = "Save the project first to keep your changes."
        alert.addButton(withTitle: "Cancel")
        alert.addButton(withTitle: "Discard Changes")
        return alert.runModal() == .alertSecondButtonReturn
    }

    func cleanupSession() {
        stopPlayback()
        engine.cleanupSession()
    }

    private func replaceProject(_ next: ProjectDocument, saved: Bool) {
        stopPlayback()
        if let project { engine.cleanup(project: project) }
        project = next
        savedProject = saved ? next : nil
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

    func presentSavePanel(exportAudio: Bool = false) {
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
            else { self?.saveProject(to: url) }
        }
        if let window = NSApp.keyWindow {
            panel.beginSheetModal(for: window, completionHandler: completion)
        } else {
            panel.begin(completionHandler: completion)
        }
    }

    func saveProject(to url: URL) {
        guard let project else { return }
        perform("Saving project…") {
            let savedURL = try await self.engine.save(project, to: url)
            self.project?.projectPath = savedURL.path
            var saved = project
            saved.projectPath = savedURL.path
            self.savedProject = saved
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
                providerID: self.selectedProviderID
            )
            self.project?.transcriptSegments = segments
            self.workspace = .transcribe
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
        if let playbackEndObserver {
            NotificationCenter.default.removeObserver(playbackEndObserver)
            self.playbackEndObserver = nil
        }
        player = nil
        isPlaying = false
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
