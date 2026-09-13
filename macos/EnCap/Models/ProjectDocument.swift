import Foundation

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
    var schemaVersion = 1
    var projectTitle = "Untitled"
    var sourceFolder: String?
    var projectPath: String?
    var workingDir: String?
    var metadata = EpisodeMetadata()
    var audioSources: [AudioSource] = []
    var chapters: [Chapter] = []
    var transcriptSegments: [TranscriptSegment] = []
    var exportSettings = ExportSettings()

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
