import AppKit
import SwiftUI

struct VideoView: View {
    @ObservedObject var store: AppStore

    var body: some View {
        if store.project == nil {
            EmptyStateView(
                "No Project",
                systemImage: "film",
                description: "Import audio in Audio mode before creating a video."
            ) {
                Button("Open Audio Mode") { store.switchWorkspace(to: .audio) }
            }
        } else if store.project?.metadata.artworkPath == nil {
            EmptyStateView(
                "Artwork Required",
                systemImage: "photo.badge.plus",
                description: "Add main artwork in Audio mode. Chapter artwork will override it when available."
            ) {
                Button("Add Artwork in Audio") { store.switchWorkspace(to: .audio) }
                    .buttonStyle(.borderedProminent)
            }
        } else {
            HSplitView {
                controls
                    .frame(minWidth: 470, idealWidth: 540)
                preview
                    .frame(minWidth: 390, maxWidth: .infinity, maxHeight: .infinity)
            }
        }
    }

    private var controls: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                chapterSelection
                formatSettings
                imageSettings
                Button(action: store.presentVideoSavePanel) {
                    Label("Export MP4…", systemImage: "square.and.arrow.up")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(store.selectedVideoChapters.isEmpty || store.isWorking)
            }
            .padding(18)
        }
    }

    private var chapterSelection: some View {
        GroupBox {
            VStack(spacing: 8) {
                HStack {
                    Text("Chapters").font(.headline)
                    Spacer()
                    Button("Select All") { store.selectAllVideoChapters(true) }
                    Button("Select None") { store.selectAllVideoChapters(false) }
                }
                ForEach(store.project?.chapters ?? []) { chapter in
                    HStack(spacing: 10) {
                        artworkThumbnail(chapter)
                        Toggle(isOn: Binding(
                            get: { store.selectedVideoChapters.contains { $0.id == chapter.id } },
                            set: { store.setVideoChapter(chapter, selected: $0) }
                        )) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(chapter.title.isEmpty ? "Chapter \(chapter.chapterNumber)" : chapter.title)
                                    .lineLimit(1)
                                Text(EnCapFormatters.timestamp(chapter.durationSeconds))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .toggleStyle(.checkbox)
                    }
                }
                Divider()
                HStack {
                    Text("Video order").font(.headline)
                    Spacer()
                    Text("Total \(EnCapFormatters.timestamp(store.selectedVideoDuration))")
                        .foregroundStyle(.secondary)
                }
                if store.selectedVideoChapters.isEmpty {
                    Text("Select at least one chapter.")
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                } else {
                    List {
                        ForEach(Array(store.selectedVideoChapters.enumerated()), id: \.element.id) { index, chapter in
                            HStack(spacing: 8) {
                            Image(systemName: "line.3.horizontal")
                                .foregroundStyle(.tertiary)
                                .accessibilityHidden(true)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(chapter.title.isEmpty ? "Chapter \(chapter.chapterNumber)" : chapter.title)
                                Text("Starts \(EnCapFormatters.timestamp(startTime(for: index))) · \(EnCapFormatters.timestamp(chapter.durationSeconds))")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Button { store.moveVideoChapter(id: chapter.id, direction: -1) } label: {
                                Image(systemName: "arrow.up")
                            }
                            .disabled(index == 0)
                            .help("Move chapter up")
                            Button { store.moveVideoChapter(id: chapter.id, direction: 1) } label: {
                                Image(systemName: "arrow.down")
                            }
                            .disabled(index == store.selectedVideoChapters.count - 1)
                            .help("Move chapter down")
                            }
                            .padding(.vertical, 3)
                            .contentShape(Rectangle())
                            .onTapGesture(count: 2) { store.jumpToVideoChapter(index) }
                            .accessibilityAction(named: "Preview chapter") { store.jumpToVideoChapter(index) }
                        }
                        .onMove(perform: store.moveVideoChapters)
                    }
                    .listStyle(.inset)
                    .frame(height: min(260, CGFloat(store.selectedVideoChapters.count * 48 + 8)))
                }
            }
            .padding(8)
        }
    }

    private var formatSettings: some View {
        GroupBox("Format") {
            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 10) {
                GridRow {
                    Text("Outlet").foregroundStyle(.secondary)
                    Picker("Outlet", selection: videoBinding(\.platform)) {
                        ForEach(platforms, id: \.self) { Text($0).tag($0) }
                    }.labelsHidden()
                }
                GridRow {
                    Text("Aspect").foregroundStyle(.secondary)
                    Picker("Aspect ratio", selection: videoBinding(\.aspect)) {
                        ForEach(aspects, id: \.self) { Text($0).tag($0) }
                    }.labelsHidden()
                }
                GridRow {
                    Text("Preset").foregroundStyle(.secondary)
                    Picker("Resolution preset", selection: presetBinding) {
                        ForEach(resolutions) { Text($0.resolution).tag(Optional($0)) }
                    }.labelsHidden()
                }
                GridRow {
                    Text("Custom size").foregroundStyle(.secondary)
                    HStack {
                        TextField("Width", value: videoBinding(\.width), format: .number).frame(width: 76)
                        Text("×").foregroundStyle(.secondary)
                        TextField("Height", value: videoBinding(\.height), format: .number).frame(width: 76)
                    }
                }
                GridRow {
                    Text("Codec").foregroundStyle(.secondary)
                    Picker("Codec", selection: videoBinding(\.codec)) {
                        Text("H.264").tag("h264")
                        Text("HEVC / H.265").tag("hevc")
                    }.labelsHidden()
                }
                GridRow {
                    Text("Encoding").foregroundStyle(.secondary)
                    Picker("Encoding", selection: videoBinding(\.encoding)) {
                        Text("Automatic").tag("automatic")
                        Text("Hardware").tag("hardware")
                        Text("Software").tag("software")
                    }.labelsHidden()
                }
                GridRow {
                    Text("Frame rate").foregroundStyle(.secondary)
                    TextField("Frames per second", value: videoBinding(\.fps), format: .number)
                        .frame(width: 76)
                }
                GridRow {
                    Text("Audio").foregroundStyle(.secondary)
                    Picker("Audio bitrate", selection: videoBinding(\.audioBitrate)) {
                        ForEach(["64k", "96k", "128k", "160k", "192k", "256k", "320k"], id: \.self) { Text($0).tag($0) }
                    }.labelsHidden()
                }
            }
            .padding(8)
        }
    }

    private var imageSettings: some View {
        GroupBox("Artwork and preview") {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 18) {
                    Toggle("Flip horizontally", isOn: videoBinding(\.flipHorizontal))
                    Toggle("Flip vertically", isOn: videoBinding(\.flipVertical))
                }
                Picker("Preview quality", selection: videoBinding(\.previewQuality)) {
                    Text("Automatic").tag("automatic")
                    Text("Low").tag("low")
                    Text("Medium").tag("medium")
                    Text("High").tag("high")
                }
            }
            .padding(8)
        }
    }

    private var preview: some View {
        VStack(spacing: 14) {
            Text("Timeline Preview").font(.title2.bold())
            GeometryReader { geometry in
                ZStack {
                    RoundedRectangle(cornerRadius: 12).fill(.black)
                    if let image = currentArtworkImage {
                        Image(nsImage: image)
                            .resizable()
                            .scaledToFill()
                            .blur(radius: 22)
                            .clipped()
                            .scaleEffect(x: flipX, y: flipY)
                        Image(nsImage: image)
                            .resizable()
                            .scaledToFit()
                            .frame(
                                width: min(canvasSize(in: geometry.size).width, canvasSize(in: geometry.size).height),
                                height: min(canvasSize(in: geometry.size).width, canvasSize(in: geometry.size).height)
                            )
                            .scaleEffect(x: flipX, y: flipY)
                    } else {
                        VStack(spacing: 8) {
                            Image(systemName: "photo").font(.largeTitle)
                            Text("No Artwork").font(.headline)
                            Text("Add artwork in Audio mode.").foregroundStyle(.secondary)
                        }
                    }
                }
                .frame(width: canvasSize(in: geometry.size).width, height: canvasSize(in: geometry.size).height)
                .clipped()
                .position(x: geometry.size.width / 2, y: geometry.size.height / 2)
                .accessibilityLabel("Video timeline preview")
            }
            .frame(minHeight: 360)
            Slider(
                value: Binding(
                    get: { min(store.videoCurrentTime, store.selectedVideoDuration) },
                    set: { store.videoCurrentTime = $0 }
                ),
                in: 0...max(store.selectedVideoDuration, 0.001),
                onEditingChanged: { editing in
                    if !editing { store.seekVideo(to: store.videoCurrentTime) }
                }
            )
            .disabled(store.selectedVideoChapters.isEmpty)
            HStack {
                Text(EnCapFormatters.timestamp(store.videoCurrentTime)).monospacedDigit()
                Spacer()
                Button(action: store.previousVideoChapter) { Image(systemName: "backward.end.fill") }
                    .help("Previous selected chapter")
                Button(action: store.toggleVideoPlayback) {
                    Image(systemName: store.isVideoPlaying ? "pause.fill" : "play.fill")
                        .frame(width: 24)
                }
                .keyboardShortcut(.space, modifiers: [])
                .help(store.isVideoPlaying ? "Pause preview" : "Play preview")
                Button(action: store.nextVideoChapter) { Image(systemName: "forward.end.fill") }
                    .help("Next selected chapter")
                Spacer()
                Text(EnCapFormatters.timestamp(store.selectedVideoDuration)).monospacedDigit()
            }
        }
        .padding(20)
    }

    private var currentArtworkImage: NSImage? {
        guard let index = store.currentVideoChapterIndex,
              store.selectedVideoChapters.indices.contains(index),
              let url = store.effectiveArtwork(for: store.selectedVideoChapters[index]) else { return nil }
        return NSImage(contentsOf: url)
    }

    private var platforms: [String] {
        store.videoPresets.map(\.platform).reduce(into: []) { if !$0.contains($1) { $0.append($1) } }
    }

    private var aspects: [String] {
        store.videoPresets.filter { $0.platform == store.project?.video.exportSettings.platform }
            .map(\.aspect).reduce(into: []) { if !$0.contains($1) { $0.append($1) } }
    }

    private var resolutions: [VideoPreset] {
        store.videoPresets.filter {
            $0.platform == store.project?.video.exportSettings.platform
                && $0.aspect == store.project?.video.exportSettings.aspect
        }
    }

    private var presetBinding: Binding<VideoPreset?> {
        Binding(
            get: {
                resolutions.first {
                    $0.width == store.project?.video.exportSettings.width
                        && $0.height == store.project?.video.exportSettings.height
                }
            },
            set: { preset in
                guard let preset else { return }
                store.project?.video.exportSettings.width = preset.width
                store.project?.video.exportSettings.height = preset.height
                store.project?.video.exportSettings.fps = preset.fps
            }
        )
    }

    private var flipX: CGFloat { store.project?.video.exportSettings.flipHorizontal == true ? -1 : 1 }
    private var flipY: CGFloat { store.project?.video.exportSettings.flipVertical == true ? -1 : 1 }

    private func videoBinding<Value>(_ keyPath: WritableKeyPath<VideoSettings, Value>) -> Binding<Value> {
        Binding(
            get: { (store.project?.video.exportSettings ?? VideoSettings())[keyPath: keyPath] },
            set: { store.project?.video.exportSettings[keyPath: keyPath] = $0 }
        )
    }

    private func startTime(for index: Int) -> Double {
        store.selectedVideoChapters.prefix(index).reduce(0) { $0 + $1.durationSeconds }
    }

    private func artworkThumbnail(_ chapter: Chapter) -> some View {
        Group {
            if let url = store.effectiveArtwork(for: chapter), let image = NSImage(contentsOf: url) {
                Image(nsImage: image).resizable().scaledToFill()
            } else {
                Image(systemName: "photo").foregroundStyle(.secondary)
            }
        }
        .frame(width: 36, height: 36)
        .clipShape(RoundedRectangle(cornerRadius: 5))
        .accessibilityHidden(true)
    }

    private func canvasSize(in available: CGSize) -> CGSize {
        let width = max(2, store.project?.video.exportSettings.width ?? 1920)
        let height = max(2, store.project?.video.exportSettings.height ?? 1080)
        let ratio = CGFloat(width) / CGFloat(height)
        let maximum = CGSize(width: max(1, available.width - 20), height: max(1, available.height - 20))
        if maximum.width / maximum.height > ratio {
            return CGSize(width: maximum.height * ratio, height: maximum.height)
        }
        return CGSize(width: maximum.width, height: maximum.width / ratio)
    }
}
