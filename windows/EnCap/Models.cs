using System.Text.Json;
using System.Text.Json.Serialization;

namespace EnCap;

public sealed class ProjectDocument
{
    public int SchemaVersion { get; set; } = 1;
    public string ProjectTitle { get; set; } = "Untitled";
    public string? SourceFolder { get; set; }
    public string? ProjectPath { get; set; }
    public string? WorkingDir { get; set; }
    public EpisodeMetadata Metadata { get; set; } = new();
    public List<AudioSource> AudioSources { get; set; } = [];
    public List<Chapter> Chapters { get; set; } = [];
    public List<TranscriptSegment> TranscriptSegments { get; set; } = [];
    public ExportSettings ExportSettings { get; set; } = new();
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
    [JsonExtensionData] public Dictionary<string, JsonElement>? Extensions { get; set; }
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

