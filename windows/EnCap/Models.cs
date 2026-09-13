using System.Text.Json;
using System.Text.Json.Serialization;

namespace EnCap;

public sealed class ProjectDocument
{
    public int SchemaVersion { get; set; } = 2;
    public string ProjectTitle { get; set; } = "Untitled";
    public string? SourceFolder { get; set; }
    public string? ProjectPath { get; set; }
    public string? WorkingDir { get; set; }
    public EpisodeMetadata Metadata { get; set; } = new();
    public List<AudioSource> AudioSources { get; set; } = [];
    public List<Chapter> Chapters { get; set; } = [];
    public List<TranscriptSegment> TranscriptSegments { get; set; } = [];
    public TranscriptSettings TranscriptSettings { get; set; } = new();
    public ExportSettings ExportSettings { get; set; } = new();
    public string ActiveMode { get; set; } = "audio";
    public VideoProjectState Video { get; set; } = new();
    public string? CompatibilityPayload { get; set; }
    [JsonExtensionData] public Dictionary<string, JsonElement>? Extensions { get; set; }
}

public sealed class EpisodeMetadata
{
    public string PodcastTitle { get; set; } = "";
    public string EpisodeTitle { get; set; } = "";
    public string Summary { get; set; } = "";
    public string? ArtworkPath { get; set; }
    [JsonExtensionData] public Dictionary<string, JsonElement>? Extensions { get; set; }
}

public sealed class AudioSource
{
    public string SourcePath { get; set; } = "";
    public string DisplayName { get; set; } = "";
    public double DurationSeconds { get; set; }
    [JsonExtensionData] public Dictionary<string, JsonElement>? Extensions { get; set; }
}

public sealed class Chapter
{
    public string Id { get; set; } = Guid.NewGuid().ToString("N");
    public double StartTimeSeconds { get; set; }
    public double DurationSeconds { get; set; }
    public int ChapterNumber { get; set; }
    public string Title { get; set; } = "";
    public string LinkUrl { get; set; } = "";
    public string? ImagePath { get; set; }
    [JsonExtensionData] public Dictionary<string, JsonElement>? Extensions { get; set; }
}

public sealed class TranscriptSegment
{
    public string Id { get; set; } = Guid.NewGuid().ToString("N");
    public double StartTimeSeconds { get; set; }
    public double EndTimeSeconds { get; set; }
    public string Speaker { get; set; } = "";
    public string Text { get; set; } = "";
    public List<TranscriptWord> Words { get; set; } = [];
    [JsonExtensionData] public Dictionary<string, JsonElement>? Extensions { get; set; }
}

public sealed class TranscriptWord
{
    public string Id { get; set; } = Guid.NewGuid().ToString("N");
    public double StartTimeSeconds { get; set; }
    public double EndTimeSeconds { get; set; }
    public string Text { get; set; } = "";
}

public sealed class TranscriptSettings
{
    public bool IncludeWordTimestamps { get; set; }
    [JsonExtensionData] public Dictionary<string, JsonElement>? Extensions { get; set; }
}

public sealed class VideoProjectState
{
    public int SchemaVersion { get; set; } = 1;
    public VideoSettings ExportSettings { get; set; } = new();
    public List<JsonElement> Compositions { get; set; } = [];
    [JsonExtensionData] public Dictionary<string, JsonElement>? Extensions { get; set; }
}

public sealed class VideoSettings
{
    public string Platform { get; set; } = "Instagram";
    public string Aspect { get; set; } = "Horizontal video (16:9)";
    public int Width { get; set; } = 1920;
    public int Height { get; set; } = 1080;
    public string Codec { get; set; } = "h264";
    public string Encoding { get; set; } = "automatic";
    public string AudioBitrate { get; set; } = "128k";
    public int Fps { get; set; } = 30;
    public bool FlipHorizontal { get; set; }
    public bool FlipVertical { get; set; }
    public string PreviewQuality { get; set; } = "automatic";
    public List<string> SelectedChapterIds { get; set; } = [];
    public bool SelectionInitialized { get; set; }
    [JsonExtensionData] public Dictionary<string, JsonElement>? Extensions { get; set; }
}

public sealed class VideoPreset
{
    public string Platform { get; set; } = "";
    public string Aspect { get; set; } = "";
    public int Width { get; set; }
    public int Height { get; set; }
    public int Fps { get; set; }
    public override string ToString() => $"{Platform} — {Aspect} — {Width} × {Height}";
}

public sealed class ExportSettings
{
    public string OutputFormat { get; set; } = "mp3";
    public string QualityPreset { get; set; } = "320k";
    public string Encoder { get; set; } = "ffmpeg";
    public int Channels { get; set; } = 2;
    [JsonExtensionData] public Dictionary<string, JsonElement>? Extensions { get; set; }
}

public sealed class TranscriptionProvider
{
    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
    public string Detail { get; set; } = "";
    public override string ToString() => $"{Name} — {Detail}";
}

public sealed class TranscriptionModelInfo
{
    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
    public string DownloadSize { get; set; } = "";
    public string Languages { get; set; } = "";
    public string Description { get; set; } = "";
    public bool Installed { get; set; }
    public bool DownloadAllowed { get; set; }
}
