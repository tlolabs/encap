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
        case audioFiles
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
    @Published private(set) var playingSourceID: AudioSource.ID?

    private let engine = EngineClient()
    @Published private(set) var sourcePlaybackRate: Float = 0
    private var sourceReadyObserver: NSKeyValueObservation?
    private var sourceTimeObserver: Any?
    private let sourceMediaControls = SourceMediaControls()
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
            saveProject()
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
            saveProject(switchingTo: target)
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
            case .audioFiles:
                addAudioFiles(urls)
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
            var project = try await self.engine.inspect(folder: url)
            let namingStyle = ChapterNamingStyle(rawValue: UserDefaults.standard.string(forKey: ChapterNamingStyle.preferenceKey) ?? "") ?? .original
            project.applyChapterNames(namingStyle)
            self.replaceProject(project, saved: false)
            self.status = "Imported \(project.audioSources.count) audio files."
        }
    }

    func addAudioFiles(_ urls: [URL]) {
        guard project != nil, !isWorking else { return }
        var known = Set(project?.audioSources.map(\.id) ?? [])
        let files = urls.map(\.standardizedFileURL).filter { known.insert($0.path).inserted }
            .sorted { $0.lastPathComponent.localizedStandardCompare($1.lastPathComponent) == .orderedAscending }
        guard !files.isEmpty else {
            status = "The selected files are already in this project."
            return
        }
        perform("Adding audio files…") {
            let imported = try await self.engine.inspect(files: files)
            guard var project = self.project else { return }
            let namingStyle = ChapterNamingStyle(rawValue: UserDefaults.standard.string(forKey: ChapterNamingStyle.preferenceKey) ?? "") ?? .original
            project.appendAudioSources(imported.audioSources, namingStyle: namingStyle)
            self.project = project
            self.status = "Added \(imported.audioSources.count) audio files."
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

    func saveProject(switchingTo: WorkspaceMode? = nil) {
        guard let project, !isWorking else { return }
        if let projectPath = project.projectPath, !projectPath.isEmpty {
            saveProject(to: URL(fileURLWithPath: projectPath), switchingTo: switchingTo)
        } else {
            presentSavePanel(switchingTo: switchingTo)
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

    func applyChapterNames(_ style: ChapterNamingStyle) {
        guard var project else { return }
        project.applyChapterNames(style)
        self.project = project
        status = "Applied \(style.rawValue) chapter names."
    }

    func addChapter() {
        guard var project else { return }
        let start = project.chapters.last.map { $0.startTimeSeconds + $0.durationSeconds } ?? 0
        let sourceIndex = project.audioSourceIndex(at: start)
        let chapterNumber = min(sourceIndex + 1, max(1, project.audioSources.count))
        let titleNumber = project.chapters.count + 1
        project.chapters.append(
            Chapter(
                startTimeSeconds: start,
                durationSeconds: 5,
                chapterNumber: chapterNumber,
                title: "Chapter \(titleNumber)"
            )
        )
        self.project = project
    }

    func removeAudioSources(ids: Set<AudioSource.ID>) {
        guard !isWorking, var project else { return }
        let count = project.audioSources.filter { ids.contains($0.id) }.count
        guard count > 0 else { return }
        // Video previews and audio previews share a player and timeline.
        stopPlayback()
        project.removeAudioSources(ids: ids)
        normalizeVideoSelection(&project)
        videoCurrentTime = 0
        self.project = project
        status = "Removed \(count) imported \(count == 1 ? "track" : "tracks") and associated chapters."
    }

    func removeChapters(at offsets: IndexSet) {

        project?.chapters.remove(atOffsets: offsets)
        renumberChapters()
    }

    func moveChapters(from offsets: IndexSet, to destination: Int) {
        project?.chapters.move(fromOffsets: offsets, toOffset: destination)
        renumberChapters()
    }

    var sourcePlaybackPosition: Double { player?.currentTime().seconds ?? 0 }

    func isPlaying(source: AudioSource) -> Bool {
        playingSourceID == source.id && isPlaying
    }

    func togglePlayback(source: AudioSource) {
        if isPlaying(source: source) { pauseSourcePlayback() }
        else { resumePlayback(source: source) }
    }

    func pauseSourcePlayback() {
        guard playingSourceID != nil else { return }
        player?.pause()
        isPlaying = false
        sourcePlaybackRate = 0
        status = "Playback paused."
        updateSourceMediaControls()
    }

    func resumePlayback(source: AudioSource) { setSourceRate(1, source: source) }

    func shuttle(source: AudioSource, direction: Float, slow: Bool) {
        let current = playingSourceID == source.id ? sourcePlaybackRate : 0
        setSourceRate(SourceShuttle.rate(current: current, direction: direction, slow: slow), source: source)
    }

    private func setSourceRate(_ rate: Float, source: AudioSource) {
        if playingSourceID != source.id || player == nil { play(source: source, rate: rate); return }
        if rate > 0, sourcePlaybackPosition >= source.durationSeconds - 0.01 { player?.seek(to: .zero) }
        sourcePlaybackRate = rate
        isPlaying = true
        applySourceRate()
    }

    private func applySourceRate() {
        guard let player, let item = player.currentItem, playingSourceID != nil else { return }
        guard item.status != .failed else {
            let message = item.error?.localizedDescription ?? "The recording could not be opened."
            stopPlayback(); status = message; return
        }
        guard item.status == .readyToPlay else { return }
        let rate = sourcePlaybackRate
        let supported = rate == 0 || rate == 1 || (rate > 0 && rate < 1 && item.canPlaySlowForward)
            || (rate > 1 && (rate <= 2 || item.canPlayFastForward))
            || (rate == -1 && item.canPlayReverse)
            || (rate < -1 && item.canPlayFastReverse)
            || (rate < 0 && rate > -1 && item.canPlaySlowReverse)
        guard supported else {
            pauseSourcePlayback()
            status = "This recording’s macOS decoder does not support \(rate)× playback."
            return
        }
        player.rate = rate
        isPlaying = rate != 0
        status = rate == 0 ? "Playback paused." : "Playing at \(rate)×."
        updateSourceMediaControls()
    }

    func play(source: AudioSource, at offset: Double = 0, rate: Float = 1) {
        stopPlayback()
        let nextPlayer = AVPlayer(url: URL(fileURLWithPath: source.sourcePath))
        player = nextPlayer
        playingSourceID = source.id
        sourcePlaybackRate = rate
        nextPlayer.seek(to: CMTime(seconds: max(0, offset), preferredTimescale: 600),
                        toleranceBefore: .zero, toleranceAfter: .zero)
        sourceReadyObserver = nextPlayer.currentItem?.observe(\.status, options: [.initial, .new]) { [weak self, weak nextPlayer] _, _ in
            Task { @MainActor in
                guard let self, self.player === nextPlayer else { return }
                self.applySourceRate()
            }
        }
        sourceTimeObserver = nextPlayer.addPeriodicTimeObserver(forInterval: CMTime(seconds: 1, preferredTimescale: 600), queue: .main) { [weak self, weak nextPlayer] _ in
            Task { @MainActor in
                guard let self, self.player === nextPlayer else { return }
                self.updateSourceMediaControls()
            }
        }
        playbackEndObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemDidPlayToEndTime, object: nextPlayer.currentItem, queue: .main
        ) { [weak self, weak nextPlayer] _ in
            Task { @MainActor in
                guard let self, self.player === nextPlayer else { return }
                self.pauseSourcePlayback()
                self.status = "Playback finished."
            }
        }
        sourceMediaControls.activate { [weak self] command, position in self?.sourceMediaCommand(command, position: position) }
        isPlaying = true
        status = "Playing \(source.displayName)."
        updateSourceMediaControls()
    }

    private func updateSourceMediaControls() {
        guard let source = project?.audioSources.first(where: { $0.id == playingSourceID }) else { return }
        sourceMediaControls.update(source: source, position: player?.currentTime().seconds ?? 0, rate: sourcePlaybackRate)
    }

    private func sourceMediaCommand(_ command: String, position: Double?) {
        guard let sources = project?.audioSources, let index = sources.firstIndex(where: { $0.id == playingSourceID }) else { return }
        switch command {
        case "play": resumePlayback(source: sources[index])
        case "toggle": togglePlayback(source: sources[index])
        case "pause": pauseSourcePlayback()
        case "stop": pauseSourcePlayback(); player?.seek(to: .zero)
        case "next", "previous":
            let next = index + (command == "next" ? 1 : -1)
            if sources.indices.contains(next) { resumePlayback(source: sources[next]) }
        case "seek":
            if let position, position.isFinite {
                player?.seek(to: CMTime(seconds: min(sources[index].durationSeconds, max(0, position)), preferredTimescale: 600))
            }
        default: break
        }
        updateSourceMediaControls()
    }

    func stopPlayback() {
        sourceReadyObserver = nil
        if let sourceTimeObserver, let player { player.removeTimeObserver(sourceTimeObserver) }
        sourceTimeObserver = nil
        sourcePlaybackRate = 0
        sourceMediaControls.deactivate()
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
        playingSourceID = nil
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
            let sourceIndex = project.audioSourceIndex(at: start)
            project.chapters[index].chapterNumber = min(sourceIndex + 1, max(1, project.audioSources.count))
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
        guard !project.audioSources.isEmpty else { return nil }
        if chapter.chapterNumber > 0 {
            let index = chapter.chapterNumber - 1
            if project.audioSources.indices.contains(index) {
                return project.audioSources[index]
            }
        }
        if project.audioSources.count == 1 {
            return project.audioSources.first
        }
        let fallbackIndex = project.audioSourceIndex(at: chapter.startTimeSeconds)
        return project.audioSources.indices.contains(fallbackIndex) ? project.audioSources[fallbackIndex] : nil
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
