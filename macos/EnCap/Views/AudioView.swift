import AppKit
import SwiftUI

struct AudioView: View {
    @ObservedObject var store: AppStore
    @Binding var sidebarVisibility: NavigationSplitViewVisibility
    @AppStorage(ChapterNamingStyle.preferenceKey) private var chapterNamingStyle = ChapterNamingStyle.original

    @StateObject private var waveforms = SourceWaveforms()
    @State private var hoveredSourceID: AudioSource.ID?
    @State private var selectedSourceIDs: Set<AudioSource.ID> = []
    @State private var pendingDeletionIDs: Set<AudioSource.ID> = []
    @State private var isDeleteConfirmationPresented = false

    var body: some View {
        if store.project == nil {
            EmptyStateView(
                "No Audio Imported",
                systemImage: "waveform",
                description: "Import a folder of WAV or AIFF recordings to create an episode."
            ) {
                Button("Import Audio Folder…") { store.presentFileImporter(.audioFolder) }
                    .keyboardShortcut("i", modifiers: .command)
                    .help("Import a folder of WAV or AIFF recordings (⌘I)")
            }
        } else {
            NavigationSplitView(columnVisibility: $sidebarVisibility) {
                sourceList
                    .modifier(WindowSidebarToggle())
                    // Apply sizing outside the toolbar wrapper so the split view
                    // receives it when restoring or revealing the sidebar.
                    .frame(minWidth: defaultSourceColumnWidth)
                    .navigationSplitViewColumnWidth(min: defaultSourceColumnWidth, ideal: defaultSourceColumnWidth, max: .infinity)
            } detail: {
                projectEditor
            }
            .navigationSplitViewStyle(.balanced)
        }
    }

    private var sourceList: some View {
        List(selection: $selectedSourceIDs) {
            Section("Source Recordings") {
                ForEach(store.project?.audioSources ?? []) { source in
                    HStack(spacing: 4) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(source.displayName).lineLimit(1)
                            HStack(spacing: 8) {
                                Text(source.fileTypeLabel)
                                SourceWaveform(peaks: waveforms.peaks[source.id] ?? [])
                                    .fill(.primary)
                                    .opacity(selectedSourceIDs.contains(source.id) ? 1 : 0.45)
                                    .frame(minWidth: 0, maxWidth: .infinity, minHeight: 12, maxHeight: 12)
                                    .accessibilityHidden(true)
                                    .allowsHitTesting(false)
                                Text(EnCapFormatters.timestamp(source.durationSeconds))
                                    .monospacedDigit()
                            }
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        Button { store.togglePlayback(source: source) } label: {
                            Image(systemName: store.isPlaying(source: source) ? "pause.fill" : "play.fill")
                                .font(.body.weight(.semibold))
                                .frame(width: 24, height: 28)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .opacity(hoveredSourceID == source.id || selectedSourceIDs.contains(source.id) ? 1 : 0.4)
                        .help(store.isPlaying(source: source)
                            ? "Pause \(source.displayName)"
                            : store.playingSourceID == source.id
                                ? "Resume \(source.displayName) from the paused position"
                                : "Play \(source.displayName)")
                        .accessibilityLabel("\(store.isPlaying(source: source) ? "Pause" : "Play") \(source.displayName)")
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
                    .onHover { hovering in
                        if hovering { hoveredSourceID = source.id }
                        else if hoveredSourceID == source.id { hoveredSourceID = nil }
                    }
                    .onAppear { waveforms.show(source.id) }
                    .onDisappear { waveforms.hide(source.id) }
                    .tag(source.id)
                }
            }
        }
        .listStyle(.sidebar)
        .contextMenu(forSelectionType: AudioSource.ID.self) { ids in
            Button("Add Audio Files…") { store.presentFileImporter(.audioFiles) }
                .help("Add WAV or AIFF recordings to this episode")
                .disabled(store.isWorking)
            if let source = selectedSource(ids) {
                Button("Play") { store.resumePlayback(source: source) }
            }
            if !ids.isEmpty {
                Divider()
                Button(ids.count == 1 ? "Delete Track…" : "Delete Tracks…", role: .destructive) {
                    requestSourceDeletion(ids)
                }
                .help("Remove selected imports and their chapters; original files stay on disk")
                .disabled(store.isWorking)
            }
        } primaryAction: { ids in
            if let source = selectedSource(ids) { store.resumePlayback(source: source) }
        }
        .overlay(SourcePlaybackKeys { key, slow in
            guard let source = selectedSource(selectedSourceIDs), !isDeleteConfirmationPresented else { return }
            switch key {
            case " ": store.togglePlayback(source: source)
            case "k": store.pauseSourcePlayback()
            case "j": store.shuttle(source: source, direction: -1, slow: slow)
            case "l": store.shuttle(source: source, direction: 1, slow: slow)
            default: break
            }
        }.allowsHitTesting(false))
        .onDeleteCommand { requestSourceDeletion(selectedSourceIDs) }
        .confirmationDialog(
            pendingDeletionIDs.count == 1 ? "Delete imported track?" : "Delete \(pendingDeletionIDs.count) imported tracks?",
            isPresented: $isDeleteConfirmationPresented,
            titleVisibility: .visible
        ) {
            Button(pendingDeletionIDs.count == 1 ? "Delete Track" : "Delete Tracks", role: .destructive) {
                store.removeAudioSources(ids: pendingDeletionIDs)
                pendingDeletionIDs = []
            }
            Button("Cancel", role: .cancel) { pendingDeletionIDs = [] }
        } message: {
            Text("The selected audio and its chapters will be removed from this project. Original files stay on disk.")
        }
        .onChange(of: store.project?.audioSources.map(\.id) ?? []) { ids in
            waveforms.retain(Set(ids))
            selectedSourceIDs.formIntersection(ids)
            pendingDeletionIDs.formIntersection(ids)
            if pendingDeletionIDs.isEmpty { isDeleteConfirmationPresented = false }
        }
        .onDisappear { waveforms.stop() }
    }

    private func selectedSource(_ ids: Set<AudioSource.ID>) -> AudioSource? {
        store.project?.audioSources.first { ids.contains($0.id) }
    }

    private var defaultSourceColumnWidth: CGFloat {
        let font = NSFont.preferredFont(forTextStyle: .body)
        let shortestNameWidth = store.project?.audioSources.map {
            ($0.displayName as NSString).size(withAttributes: [.font: font]).width
        }.min() ?? 140
        // Include the 24-point playback target, its 4-point gap, and the
        // sidebar's row, container, and scrollbar space (60 points).
        return max(180, ceil(shortestNameWidth) + 88)
    }

    private func requestSourceDeletion(_ ids: Set<AudioSource.ID>) {
        guard !store.isWorking else { return }
        let knownIDs = Set(store.project?.audioSources.map(\.id) ?? [])
        pendingDeletionIDs = ids.intersection(knownIDs)
        isDeleteConfirmationPresented = !pendingDeletionIDs.isEmpty
    }

    private var projectEditor: some View {
        VStack(alignment: .leading, spacing: 16) {
            metadataSection
            encodingSection
            chaptersSection
                .frame(maxHeight: .infinity)
        }
        .padding(.horizontal, 20)
        .padding(.top, 16)
        .padding(.bottom, 8)
    }

    private var metadataSection: some View {
        GroupBox("Episode") {
            HStack(alignment: .top, spacing: 16) {
                Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 10) {
                    GridRow {
                        Text("Podcast").foregroundStyle(.secondary)
                        TextField("Podcast title", text: metadataBinding(\.podcastTitle))
                    }
                    GridRow {
                        Text("Episode").foregroundStyle(.secondary)
                        TextField("Episode title", text: metadataBinding(\.episodeTitle))
                    }
                    GridRow(alignment: .top) {
                        Text("Summary").foregroundStyle(.secondary).padding(.top, 5)
                        TextEditor(text: metadataBinding(\.summary))
                            .font(.body)
                            .accessibilityLabel("Episode summary")
                            .frame(height: 82)
                            .overlay(RoundedRectangle(cornerRadius: 5).stroke(.quaternary))
                    }
                    GridRow {
                        Text("Artwork").foregroundStyle(.secondary)
                        HStack {
                            Text(store.project?.metadata.artworkPath.map { URL(fileURLWithPath: $0).lastPathComponent } ?? "None")
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                                .truncationMode(.middle)
                            Spacer()
                            Button("Choose…") { store.presentFileImporter(.artwork) }
                                .help("Choose or replace the episode’s album artwork")
                        }
                    }
                }
                EpisodeArtworkPreview(path: store.project?.metadata.artworkPath)
            }
            .padding(8)
        }
    }

    private var encodingSection: some View {
        GroupBox("Encoding") {
            HStack(spacing: 18) {
                Picker("Format", selection: exportBinding(\.outputFormat)) {
                    Text("MP3").tag("mp3")
                    Text("AAC / M4A").tag("aac")
                }
                .help("Choose the exported audio file format")
                Picker("Encoder", selection: exportBinding(\.encoder)) {
                    if store.project?.exportSettings.outputFormat == "aac" {
                        Text("Apple AudioToolbox").tag("audio_toolbox")
                        Text("FFmpeg AAC").tag("ffmpeg")
                    } else {
                        Text("LAME").tag("lame")
                        Text("FFmpeg MP3").tag("ffmpeg")
                    }
                }
                .help("Choose the encoder used to create the audio file")
                Picker("Channels", selection: exportBinding(\.channels)) {
                    Text("Mono").tag(1)
                    Text("Stereo").tag(2)
                }
                .help("Export one audio channel (Mono) or two (Stereo)")
                Picker("Bitrate", selection: exportBinding(\.qualityPreset)) {
                    ForEach(bitrates, id: \.self) { Text($0).tag($0) }
                }
                .help("Choose audio quality; higher bitrates produce larger files")
            }
            .padding(8)
        }
    }

    private var chaptersSection: some View {
        GroupBox {
            VStack(spacing: 0) {
                HStack {
                    Text("Chapters").font(.headline)
                    Picker("Names", selection: $chapterNamingStyle) {
                        ForEach(ChapterNamingStyle.allCases) { style in
                            Text(style.rawValue).tag(style)
                        }
                    }
                    .fixedSize()
                    .help("Choose names for new imports, or apply them to the current chapters. Choose Custom to type your own titles below.")
                    Button("Apply") { store.applyChapterNames(chapterNamingStyle) }
                        .disabled(chapterNamingStyle == .custom || (store.project?.chapters.isEmpty ?? true))
                        .help(chapterNamingStyle == .custom
                            ? "Custom names are edited directly in the chapter title fields below"
                            : "Replace all chapter titles with the selected naming style. Time rounds filename timestamps to the nearest minute; other filenames keep their original names.")
                    Spacer()
                    Button { store.addChapter() } label: { Label("Add", systemImage: "plus") }
                        .help("Add a chapter at the end of the episode")
                }
                .padding(8)
                Divider()
                List {
                    ForEach(chapterBindings) { $chapter in
                        let rowNumber = (store.project?.chapters.firstIndex(where: { $0.id == chapter.id }) ?? 0) + 1
                        ChapterRow(
                            displayNumber: rowNumber,
                            chapter: $chapter,
                            didRename: { chapterNamingStyle = .custom },
                            chooseArtwork: { store.chooseChapterArtwork(for: chapter.id) }
                        )
                    }
                    .onDelete(perform: store.removeChapters)
                    .onMove(perform: store.moveChapters)
                }
                .listStyle(.inset)
                .frame(minHeight: 150, maxHeight: .infinity)
            }
        }
    }

    private var chapterBindings: Binding<[Chapter]> {
        Binding(
            get: { store.project?.chapters ?? [] },
            set: { store.project?.chapters = $0 }
        )
    }

    private var bitrates: [String] { store.project?.exportSettings.bitrates ?? [] }

    private func metadataBinding<Value>(_ keyPath: WritableKeyPath<EpisodeMetadata, Value>) -> Binding<Value> {
        Binding(
            get: { (store.project?.metadata ?? EpisodeMetadata())[keyPath: keyPath] },
            set: { store.project?.metadata[keyPath: keyPath] = $0 }
        )
    }

    private func exportBinding<Value>(_ keyPath: WritableKeyPath<ExportSettings, Value>) -> Binding<Value> {
        Binding(
            get: { (store.project?.exportSettings ?? ExportSettings())[keyPath: keyPath] },
            set: {
                store.project?.exportSettings[keyPath: keyPath] = $0
                store.project?.exportSettings.normalizeSelection()
            }
        )
    }
}

private struct ChapterRow: View {
    let displayNumber: Int
    @Binding var chapter: Chapter
    let didRename: () -> Void
    let chooseArtwork: () -> Void

    var body: some View {
        Grid(alignment: .leading, horizontalSpacing: 10) {
            GridRow {
                Text(String(displayNumber))
                    .foregroundStyle(.secondary)
                    .frame(width: 28, alignment: .trailing)
                Text(EnCapFormatters.timestamp(chapter.startTimeSeconds))
                    .monospacedDigit()
                    .foregroundStyle(.secondary)
                    .frame(width: 62, alignment: .leading)
                TextField("Chapter title", text: Binding(
                    get: { chapter.title },
                    set: {
                        chapter.title = $0
                        didRename()
                    }
                ))
                TextField("Link", text: $chapter.linkUrl)
                    .frame(minWidth: 160)
                Button(action: chooseArtwork) {
                    Image(systemName: chapter.imagePath == nil ? "photo.badge.plus" : "photo.fill")
                }
                .help(chapter.imagePath == nil ? "Add chapter artwork" : "Replace chapter artwork")
                .accessibilityLabel(chapter.imagePath == nil ? "Add chapter artwork" : "Replace chapter artwork")
            }
        }
        .padding(.vertical, 3)
    }
}

/// The titlebar accessory owns the toggle on macOS 14 and later.
private struct WindowSidebarToggle: ViewModifier {
    @ViewBuilder
    func body(content: Content) -> some View {
        if #available(macOS 14.0, *) {
            content.toolbar(removing: .sidebarToggle)
        } else {
            content
        }
    }
}
