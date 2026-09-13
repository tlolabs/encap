import Foundation

enum WorkspaceMode: String, CaseIterable, Identifiable, Codable {
    case audio = "Audio"
    case transcript = "Transcript"
    case video = "Video"

    var id: String { rawValue }

    init(from decoder: Decoder) throws {
        let value = try decoder.singleValueContainer().decode(String.self).lowercased()
        switch value {
        case "audio", "assemble", "process", "process_audio": self = .audio
        case "transcript", "transcribe": self = .transcript
        case "video": self = .video
        default: self = .audio
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(rawValue.lowercased())
    }
}

struct AudioSource: Codable, Identifiable, Hashable {
    var sourcePath: String
    var displayName: String
    var durationSeconds: Double

    var id: String { sourcePath }
}

struct Chapter: Codable, Identifiable, Hashable {
    var id: String
    var startTimeSeconds: Double
    var durationSeconds: Double
    var chapterNumber: Int
    var title: String
    var linkUrl: String
    var imagePath: String?

    init(
        id: String = UUID().uuidString,
        startTimeSeconds: Double,
        durationSeconds: Double,
        chapterNumber: Int,
        title: String,
        linkUrl: String = "",
        imagePath: String? = nil
    ) {
        self.id = id
        self.startTimeSeconds = startTimeSeconds
        self.durationSeconds = durationSeconds
        self.chapterNumber = chapterNumber
        self.title = title
        self.linkUrl = linkUrl
        self.imagePath = imagePath
    }
}

struct EpisodeMetadata: Codable, Hashable {
    var podcastTitle = ""
    var episodeTitle = ""
    var summary = ""
    var artworkPath: String?
}

struct TranscriptSegment: Codable, Identifiable, Hashable {
    var id: String
    var startTimeSeconds: Double
    var endTimeSeconds: Double
    var speaker: String
    var text: String
    var words: [TranscriptWord] = []

    enum CodingKeys: String, CodingKey {
        case id, startTimeSeconds, endTimeSeconds, speaker, text, words
    }

    init(
        id: String,
        startTimeSeconds: Double,
        endTimeSeconds: Double,
        speaker: String,
        text: String,
        words: [TranscriptWord] = []
    ) {
        self.id = id
        self.startTimeSeconds = startTimeSeconds
        self.endTimeSeconds = endTimeSeconds
        self.speaker = speaker
        self.text = text
        self.words = words
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        startTimeSeconds = try container.decode(Double.self, forKey: .startTimeSeconds)
        endTimeSeconds = try container.decode(Double.self, forKey: .endTimeSeconds)
        speaker = try container.decodeIfPresent(String.self, forKey: .speaker) ?? ""
        text = try container.decodeIfPresent(String.self, forKey: .text) ?? ""
        words = try container.decodeIfPresent([TranscriptWord].self, forKey: .words) ?? []
    }
}

struct TranscriptWord: Codable, Identifiable, Hashable {
    var id: String
    var startTimeSeconds: Double
    var endTimeSeconds: Double
    var text: String
}

struct TranscriptSettings: Codable, Hashable {
    var includeWordTimestamps = false
}

struct VideoPreset: Codable, Identifiable, Hashable {
    var platform: String
    var aspect: String
    var width: Int
    var height: Int
    var fps: Int

    var id: String { "\(platform)|\(aspect)|\(width)x\(height)|\(fps)" }
    var resolution: String { "\(width) × \(height)" }
}

struct VideoEncoderCapability: Codable, Identifiable, Hashable {
    var codec: String
    var encoder: String
    var hardware: Bool
    var id: String { encoder }
}

struct VideoCapabilities: Codable, Hashable {
    var encoders: [VideoEncoderCapability] = []
}

struct VideoSettings: Codable, Hashable {
    var platform = "Instagram"
    var aspect = "Horizontal video (16:9)"
    var width = 1920
    var height = 1080
    var codec = "h264"
    var encoding = "automatic"
    var audioBitrate = "128k"
    var fps = 30
    var flipHorizontal = false
    var flipVertical = false
    var previewQuality = "automatic"
    var selectedChapterIds: [String] = []
    var selectionInitialized = false

    enum CodingKeys: String, CodingKey {
        case platform, aspect, width, height, codec, encoding, audioBitrate, fps
        case flipHorizontal, flipVertical, previewQuality, selectedChapterIds, selectionInitialized
    }

    init() {}

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        platform = try container.decodeIfPresent(String.self, forKey: .platform) ?? platform
        aspect = try container.decodeIfPresent(String.self, forKey: .aspect) ?? aspect
        width = try container.decodeIfPresent(Int.self, forKey: .width) ?? width
        height = try container.decodeIfPresent(Int.self, forKey: .height) ?? height
        codec = try container.decodeIfPresent(String.self, forKey: .codec) ?? codec
        encoding = try container.decodeIfPresent(String.self, forKey: .encoding) ?? encoding
        audioBitrate = try container.decodeIfPresent(String.self, forKey: .audioBitrate) ?? audioBitrate
        fps = try container.decodeIfPresent(Int.self, forKey: .fps) ?? fps
        flipHorizontal = try container.decodeIfPresent(Bool.self, forKey: .flipHorizontal) ?? flipHorizontal
        flipVertical = try container.decodeIfPresent(Bool.self, forKey: .flipVertical) ?? flipVertical
        previewQuality = try container.decodeIfPresent(String.self, forKey: .previewQuality) ?? previewQuality
        selectedChapterIds = try container.decodeIfPresent([String].self, forKey: .selectedChapterIds) ?? []
        selectionInitialized = try container.decodeIfPresent(Bool.self, forKey: .selectionInitialized) ?? false
    }
}

enum JSONValue: Codable, Hashable {
    case string(String)
    case number(Double)
    case boolean(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null }
        else if let value = try? container.decode(Bool.self) { self = .boolean(value) }
        else if let value = try? container.decode(Double.self) { self = .number(value) }
        else if let value = try? container.decode(String.self) { self = .string(value) }
        else if let value = try? container.decode([String: JSONValue].self) { self = .object(value) }
        else { self = .array(try container.decode([JSONValue].self)) }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .boolean(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .null: try container.encodeNil()
        }
    }
}

struct VideoProjectState: Codable, Hashable {
    var schemaVersion = 1
    var exportSettings = VideoSettings()
    var compositions: [JSONValue] = []

    enum CodingKeys: String, CodingKey {
        case schemaVersion, exportSettings, compositions
    }

    init() {}

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try container.decodeIfPresent(Int.self, forKey: .schemaVersion) ?? 1
        exportSettings = try container.decodeIfPresent(VideoSettings.self, forKey: .exportSettings) ?? VideoSettings()
        compositions = try container.decodeIfPresent([JSONValue].self, forKey: .compositions) ?? []
    }
}

struct ExportSettings: Codable, Hashable {
    var outputFormat = "mp3"
    var qualityPreset = "320k"
    var encoder = "lame"
    var channels = 2

    var fileExtension: String { ["aac", "m4a"].contains(outputFormat) ? "m4a" : "mp3" }

    var bitrates: [String] {
        if outputFormat == "aac" {
            return channels == 1 ? ["48k", "64k", "80k", "96k", "128k", "160k"]
                : ["64k", "96k", "128k", "160k", "192k", "256k", "320k"]
        }
        return channels == 1 ? ["64k", "80k", "96k", "112k", "128k", "160k"]
            : ["96k", "128k", "160k", "192k", "224k", "256k", "320k"]
    }

    mutating func normalizeSelection() {
        if outputFormat == "m4a" { outputFormat = "aac" }
        let encoders = outputFormat == "aac" ? ["ffmpeg", "audio_toolbox"] : ["lame", "ffmpeg"]
        if !encoders.contains(encoder) { encoder = encoders[0] }
        if !bitrates.contains(qualityPreset) { qualityPreset = bitrates.last ?? "128k" }
    }
}

struct ProjectDocument: Codable, Hashable {
    var schemaVersion = 2
    var projectTitle = "Untitled"
    var sourceFolder: String?
    var projectPath: String?
    var workingDir: String?
    var metadata = EpisodeMetadata()
    var audioSources: [AudioSource] = []
    var chapters: [Chapter] = []
    var transcriptSegments: [TranscriptSegment] = []
    var transcriptSettings = TranscriptSettings()
    var exportSettings = ExportSettings()
    var activeMode = WorkspaceMode.audio
    var video = VideoProjectState()
    var compatibilityPayload: String?

    enum CodingKeys: String, CodingKey {
        case schemaVersion, projectTitle, sourceFolder, projectPath, workingDir, metadata
        case audioSources, chapters, transcriptSegments, transcriptSettings, exportSettings
        case activeMode, workspace, video, compatibilityPayload
    }

    init() {}

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try container.decodeIfPresent(Int.self, forKey: .schemaVersion) ?? 1
        projectTitle = try container.decodeIfPresent(String.self, forKey: .projectTitle) ?? "Untitled"
        sourceFolder = try container.decodeIfPresent(String.self, forKey: .sourceFolder)
        projectPath = try container.decodeIfPresent(String.self, forKey: .projectPath)
        workingDir = try container.decodeIfPresent(String.self, forKey: .workingDir)
        metadata = try container.decodeIfPresent(EpisodeMetadata.self, forKey: .metadata) ?? EpisodeMetadata()
        audioSources = try container.decodeIfPresent([AudioSource].self, forKey: .audioSources) ?? []
        chapters = try container.decodeIfPresent([Chapter].self, forKey: .chapters) ?? []
        transcriptSegments = try container.decodeIfPresent([TranscriptSegment].self, forKey: .transcriptSegments) ?? []
        transcriptSettings = try container.decodeIfPresent(TranscriptSettings.self, forKey: .transcriptSettings) ?? TranscriptSettings()
        exportSettings = try container.decodeIfPresent(ExportSettings.self, forKey: .exportSettings) ?? ExportSettings()
        activeMode = try container.decodeIfPresent(WorkspaceMode.self, forKey: .activeMode)
            ?? container.decodeIfPresent(WorkspaceMode.self, forKey: .workspace)
            ?? .audio
        video = try container.decodeIfPresent(VideoProjectState.self, forKey: .video) ?? VideoProjectState()
        compatibilityPayload = try container.decodeIfPresent(String.self, forKey: .compatibilityPayload)
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(schemaVersion, forKey: .schemaVersion)
        try container.encode(projectTitle, forKey: .projectTitle)
        try container.encodeIfPresent(sourceFolder, forKey: .sourceFolder)
        try container.encodeIfPresent(projectPath, forKey: .projectPath)
        try container.encodeIfPresent(workingDir, forKey: .workingDir)
        try container.encode(metadata, forKey: .metadata)
        try container.encode(audioSources, forKey: .audioSources)
        try container.encode(chapters, forKey: .chapters)
        try container.encode(transcriptSegments, forKey: .transcriptSegments)
        try container.encode(transcriptSettings, forKey: .transcriptSettings)
        try container.encode(exportSettings, forKey: .exportSettings)
        try container.encode(activeMode, forKey: .activeMode)
        try container.encode(video, forKey: .video)
        try container.encodeIfPresent(compatibilityPayload, forKey: .compatibilityPayload)
    }

    var outputBaseName: String {
        let value = metadata.episodeTitle.isEmpty ? projectTitle : metadata.episodeTitle
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-_ "))
        let cleaned = value.unicodeScalars.map { allowed.contains($0) ? Character(String($0)) : "-" }
        let words = String(cleaned).split(whereSeparator: { $0.isWhitespace })
        return words.isEmpty ? "encap-output" : words.joined(separator: "-")
    }
}

struct TranscriptionProvider: Codable, Identifiable, Hashable {
    var id: String
    var name: String
    var detail: String
}

struct TranscriptionModelInfo: Codable, Identifiable, Hashable {
    var id: String
    var name: String
    var downloadSize: String
    var languages: String
    var description: String
    var installed: Bool
    var downloadAllowed: Bool
}
