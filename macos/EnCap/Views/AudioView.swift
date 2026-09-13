import SwiftUI

struct AudioView: View {
    @ObservedObject var store: AppStore

    var body: some View {
        if store.project == nil {
            EmptyStateView(
                "No Audio Imported",
                systemImage: "waveform",
                description: "Import a folder of WAV or AIFF recordings to create an episode."
            ) {
                Button("Import Audio Folder…") { store.presentFileImporter(.audioFolder) }
                    .keyboardShortcut("i", modifiers: .command)
            }
        } else {
            NavigationSplitView {
                sourceList
            } detail: {
                projectEditor
            }
            .navigationSplitViewStyle(.balanced)
        }
    }

    private var sourceList: some View {
        List {
            Section("Source Recordings") {
                ForEach(store.project?.audioSources ?? []) { source in
                    Button { store.play(source: source) } label: {
                        HStack(spacing: 10) {
                            Image(systemName: "waveform")
                                .foregroundStyle(.secondary)
                                .frame(width: 16)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(source.displayName).lineLimit(1)
                                Text(EnCapFormatters.timestamp(source.durationSeconds))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Image(systemName: "play.fill")
                                .font(.caption)
                                .foregroundStyle(.tertiary)
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .listStyle(.sidebar)
        .navigationSplitViewColumnWidth(min: 220, ideal: 260, max: 340)
    }

    private var projectEditor: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                metadataSection
                encodingSection
                chaptersSection
            }
            .padding(20)
        }
    }

    private var metadataSection: some View {
        GroupBox("Episode") {
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
                        .frame(minHeight: 82)
                        .overlay(RoundedRectangle(cornerRadius: 5).stroke(.quaternary))
                }
                GridRow {
                    Text("Artwork").foregroundStyle(.secondary)
                    HStack {
                        Text(store.project?.metadata.artworkPath.map { URL(fileURLWithPath: $0).lastPathComponent } ?? "None")
                            .foregroundStyle(.secondary)
                        Spacer()
                        Button("Choose…") { store.presentFileImporter(.artwork) }
                    }
                }
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
                Picker("Encoder", selection: exportBinding(\.encoder)) {
                    if store.project?.exportSettings.outputFormat == "aac" {
                        Text("Apple AudioToolbox").tag("audio_toolbox")
                        Text("FFmpeg AAC").tag("ffmpeg")
                    } else {
                        Text("LAME").tag("lame")
                        Text("FFmpeg MP3").tag("ffmpeg")
                    }
                }
                Picker("Channels", selection: exportBinding(\.channels)) {
                    Text("Mono").tag(1)
                    Text("Stereo").tag(2)
                }
                Picker("Bitrate", selection: exportBinding(\.qualityPreset)) {
                    ForEach(bitrates, id: \.self) { Text($0).tag($0) }
                }
            }
            .padding(8)
        }
    }

    private var chaptersSection: some View {
        GroupBox {
            VStack(spacing: 0) {
                HStack {
                    Text("Chapters").font(.headline)
                    Spacer()
                    Button { store.addChapter() } label: { Label("Add", systemImage: "plus") }
                }
                .padding(8)
                Divider()
                List {
                    ForEach(chapterBindings) { $chapter in
                        ChapterRow(
                            chapter: $chapter,
                            chooseArtwork: { store.chooseChapterArtwork(for: chapter.id) }
                        )
                    }
                    .onDelete(perform: store.removeChapters)
                    .onMove(perform: store.moveChapters)
                }
                .listStyle(.inset)
                .frame(minHeight: 220)
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
    @Binding var chapter: Chapter
    let chooseArtwork: () -> Void

    var body: some View {
        Grid(alignment: .leading, horizontalSpacing: 10) {
            GridRow {
                Text(String(chapter.chapterNumber))
                    .foregroundStyle(.secondary)
                    .frame(width: 28, alignment: .trailing)
                Text(EnCapFormatters.timestamp(chapter.startTimeSeconds))
                    .monospacedDigit()
                    .foregroundStyle(.secondary)
                    .frame(width: 62, alignment: .leading)
                TextField("Chapter title", text: $chapter.title)
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
