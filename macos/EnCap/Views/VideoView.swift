import AppKit
import SwiftUI

struct VideoView: View {
    @ObservedObject var store: AppStore
    @Binding var sidebarVisibility: NavigationSplitViewVisibility
    @State private var advancedFormatExpanded = true
    @State private var artworkOptionsExpanded = true

    var body: some View {
        if store.project == nil {
            EmptyStateView(
                "No Project",
                systemImage: "film",
                description: "Import audio in Audio mode before creating a video."
            ) {
                Button("Open Audio Mode") { store.switchWorkspace(to: .audio) }
                    .help("Open Audio mode to import recordings and prepare an episode")
            }
        } else {
            HSplitView {
                if sidebarVisibility != .detailOnly {
                    VideoChapterSidebar(store: store)
                        .frame(minWidth: 230, idealWidth: 290, maxWidth: 420)
                }
                videoDetail
                    .frame(minWidth: 540, maxWidth: .infinity, maxHeight: .infinity)
            }
        }
    }

    @ViewBuilder
    private var videoDetail: some View {
        if store.project?.metadata.artworkPath == nil {
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
                    .frame(minWidth: 260, idealWidth: 300, maxWidth: 370)
                preview
                    .frame(minWidth: 260, maxWidth: .infinity, maxHeight: .infinity)
            }
        }
    }

    private var controls: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                formatSettings
                imageSettings
            }
            .padding(14)
            .padding(.top, 12)
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
                    .help("Choose an outlet to see its video presets")
                }
                GridRow {
                    Text("Aspect").foregroundStyle(.secondary)
                    Picker("Aspect ratio", selection: videoBinding(\.aspect)) {
                        ForEach(aspects, id: \.self) { Text($0).tag($0) }
                    }.labelsHidden()
                    .help("Choose the video’s aspect ratio")
                }
                GridRow {
                    Text("Preset").foregroundStyle(.secondary)
                    Picker("Resolution preset", selection: presetBinding) {
                        ForEach(resolutions) { Text($0.resolution).tag(Optional($0)) }
                    }.labelsHidden()
                    .help("Apply a preset video resolution and frame rate")
                }
            }
            .padding(8)
            DisclosureGroup(isExpanded: $advancedFormatExpanded) {
                Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 10) {
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
                        .help("Choose the compression format for the exported video")
                    }
                    GridRow {
                        Text("Encoding").foregroundStyle(.secondary)
                        Picker("Encoding", selection: videoBinding(\.encoding)) {
                            Text("Automatic").tag("automatic")
                            Text("Hardware").tag("hardware")
                            Text("Software").tag("software")
                        }.labelsHidden()
                        .help("Choose automatic, hardware, or software video encoding")
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
                        .help("Choose the audio bitrate for the exported video")
                    }
                }
                .padding(.top, 10)
            } label: {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Advanced format")
                    Text(formatSummary)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(8)
        }
    }

    private var imageSettings: some View {
        GroupBox {
            DisclosureGroup(isExpanded: $artworkOptionsExpanded) {
                VStack(alignment: .leading, spacing: 10) {
                    VStack(alignment: .leading, spacing: 10) {
                        Toggle("Flip horizontally", isOn: videoBinding(\.flipHorizontal))
                            .help("Mirror the artwork from left to right")
                        Toggle("Flip vertically", isOn: videoBinding(\.flipVertical))
                            .help("Flip the artwork upside down")
                    }
                    Picker("Preview quality", selection: videoBinding(\.previewQuality)) {
                        Text("Automatic").tag("automatic")
                        Text("Low").tag("low")
                        Text("Medium").tag("medium")
                        Text("High").tag("high")
                    }
                    .help("Choose the project’s preview quality setting")
                }
                .padding(.top, 10)
            } label: {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Artwork and preview").font(.headline)
                    Text(artworkSummary)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(8)
        }
    }

    private var formatSummary: String {
        guard let settings = store.project?.video.exportSettings else { return "" }
        let codec = settings.codec == "hevc" ? "HEVC" : "H.264"
        return "\(settings.width) × \(settings.height) · \(settings.fps) fps · \(codec)"
    }

    private var artworkSummary: String {
        guard let settings = store.project?.video.exportSettings else { return "" }
        let flips = [settings.flipHorizontal ? "horizontal flip" : nil,
                     settings.flipVertical ? "vertical flip" : nil].compactMap { $0 }
        return "\(flips.isEmpty ? "No flips" : flips.joined(separator: ", ")) · \(settings.previewQuality.capitalized) preview"
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
            .frame(minHeight: 180)
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
            .help("Scrub through the selected chapters to preview a different time")
            .accessibilityLabel("Video timeline position")
            .accessibilityValue(EnCapFormatters.timestamp(store.videoCurrentTime))
            HStack {
                Text(EnCapFormatters.timestamp(store.videoCurrentTime)).monospacedDigit()
                Spacer()
                Button(action: store.previousVideoChapter) { Image(systemName: "backward.end.fill") }
                    .help("Previous selected chapter")
                    .accessibilityLabel("Previous selected chapter")
                Button(action: store.toggleVideoPlayback) {
                    Image(systemName: store.isVideoPlaying ? "pause.fill" : "play.fill")
                        .frame(width: 24)
                }
                .keyboardShortcut(.space, modifiers: [])
                .help(store.isVideoPlaying ? "Pause video preview (Space)" : "Play video preview (Space)")
                .accessibilityLabel(store.isVideoPlaying ? "Pause video preview" : "Play video preview")
                Button(action: store.nextVideoChapter) { Image(systemName: "forward.end.fill") }
                    .help("Next selected chapter")
                    .accessibilityLabel("Next selected chapter")
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
