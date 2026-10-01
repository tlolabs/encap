using System.Text.Json;
using System.Text.Json.Serialization;

namespace EnCap;

public sealed class ProjectDocument : ObservableObject
{
    private int _schemaVersion = 2;
    public int SchemaVersion
    {
        get => _schemaVersion; set => Set(ref _schemaVersion, value);
    }
    private string _projectTitle = "Untitled";
    public string ProjectTitle
    {
        get => _projectTitle; set => Set(ref _projectTitle, value);
    }
    private string? _sourceFolder;
    public string? SourceFolder
    {
        get => _sourceFolder; set => Set(ref _sourceFolder, value);
    }
    private string? _projectPath;
    public string? ProjectPath
    {
        get => _projectPath; set => Set(ref _projectPath, value);
    }
    private string? _workingDir;
    public string? WorkingDir
    {
        get => _workingDir; set => Set(ref _workingDir, value);
    }
    private EpisodeMetadata _metadata = new();
    public EpisodeMetadata Metadata
    {
        get => _metadata; set => Set(ref _metadata, value);
    }
    private List<AudioSource> _audioSources = [];
    public List<AudioSource> AudioSources
    {
        get => _audioSources; set => Set(ref _audioSources, value);
    }
    private List<Chapter> _chapters = [];
    public List<Chapter> Chapters
    {
        get => _chapters; set => Set(ref _chapters, value);
    }
    private List<TranscriptSegment> _transcriptSegments = [];
    public List<TranscriptSegment> TranscriptSegments
    {
        get => _transcriptSegments; set => Set(ref _transcriptSegments, value);
    }
    private TranscriptSettings _transcriptSettings = new();
    public TranscriptSettings TranscriptSettings
    {
        get => _transcriptSettings; set => Set(ref _transcriptSettings, value);
    }
    private ExportSettings _exportSettings = new();
    public ExportSettings ExportSettings
    {
        get => _exportSettings; set => Set(ref _exportSettings, value);
    }
    private string _activeMode = "audio";
    public string ActiveMode
    {
        get => _activeMode; set => Set(ref _activeMode, value);
    }
    private VideoProjectState _video = new();
    public VideoProjectState Video
    {
        get => _video; set => Set(ref _video, value);
    }
    private string? _compatibilityPayload;
    public string? CompatibilityPayload
    {
        get => _compatibilityPayload; set => Set(ref _compatibilityPayload, value);
    }
    private Dictionary<string, JsonElement>? _value15;
    [JsonExtensionData]
    public Dictionary<string, JsonElement>? Extensions
    {
        get => _value15; set => Set(ref _value15, value);
    }
}

public sealed class EpisodeMetadata : ObservableObject
{
    private string _podcastTitle = "";
    public string PodcastTitle
    {
        get => _podcastTitle; set => Set(ref _podcastTitle, value);
    }
    private string _episodeTitle = "";
    public string EpisodeTitle
    {
        get => _episodeTitle; set => Set(ref _episodeTitle, value);
    }
    private string _summary = "";
    public string Summary
    {
        get => _summary; set => Set(ref _summary, value);
    }
    private string? _artworkPath;
    public string? ArtworkPath
    {
        get => _artworkPath; set => Set(ref _artworkPath, value);
    }
    private Dictionary<string, JsonElement>? _value20;
    [JsonExtensionData]
    public Dictionary<string, JsonElement>? Extensions
    {
        get => _value20; set => Set(ref _value20, value);
    }
}

public sealed class AudioSource : ObservableObject
{
    private string _sourcePath = "";
    public string SourcePath
    {
        get => _sourcePath; set => Set(ref _sourcePath, value);
    }
    private string _displayName = "";
    public string DisplayName
    {
        get => _displayName; set => Set(ref _displayName, value);
    }
    private double _durationSeconds;
    public double DurationSeconds
    {
        get => _durationSeconds; set => Set(ref _durationSeconds, value);
    }
    private Dictionary<string, JsonElement>? _value24;
    [JsonExtensionData]
    public Dictionary<string, JsonElement>? Extensions
    {
        get => _value24; set => Set(ref _value24, value);
    }
}

public sealed class Chapter : ObservableObject
{
    public override string ToString() => Title;
    private string _id = Guid.NewGuid().ToString("N");
    public string Id
    {
        get => _id; set => Set(ref _id, value);
    }
    private double _startTimeSeconds;
    public double StartTimeSeconds
    {
        get => _startTimeSeconds; set => Set(ref _startTimeSeconds, value);
    }
    private double _durationSeconds;
    public double DurationSeconds
    {
        get => _durationSeconds; set => Set(ref _durationSeconds, value);
    }
    private int _chapterNumber;
    public int ChapterNumber
    {
        get => _chapterNumber; set => Set(ref _chapterNumber, value);
    }
    private int _displayNumber;
    [JsonIgnore]
    public int DisplayNumber
    {
        get => _displayNumber; set => Set(ref _displayNumber, value);
    }
    private string _title = "";
    public string Title
    {
        get => _title; set => Set(ref _title, value);
    }
    private string _linkUrl = "";
    public string LinkUrl
    {
        get => _linkUrl; set => Set(ref _linkUrl, value);
    }
    private string? _imagePath;
    public string? ImagePath
    {
        get => _imagePath; set => Set(ref _imagePath, value);
    }
    private Dictionary<string, JsonElement>? _value33;
    [JsonExtensionData]
    public Dictionary<string, JsonElement>? Extensions
    {
        get => _value33; set => Set(ref _value33, value);
    }
}

public sealed class TranscriptSegment : ObservableObject
{
    private string _id = Guid.NewGuid().ToString("N");
    public string Id
    {
        get => _id; set => Set(ref _id, value);
    }
    private double _startTimeSeconds;
    public double StartTimeSeconds
    {
        get => _startTimeSeconds; set => Set(ref _startTimeSeconds, value);
    }
    private double _endTimeSeconds;
    public double EndTimeSeconds
    {
        get => _endTimeSeconds; set => Set(ref _endTimeSeconds, value);
    }
    private string _speaker = "";
    public string Speaker
    {
        get => _speaker; set => Set(ref _speaker, value);
    }
    private string _text = "";
    public string Text
    {
        get => _text; set => Set(ref _text, value);
    }
    private List<TranscriptWord> _words = [];
    public List<TranscriptWord> Words
    {
        get => _words; set => Set(ref _words, value);
    }
    private Dictionary<string, JsonElement>? _value40;
    [JsonExtensionData]
    public Dictionary<string, JsonElement>? Extensions
    {
        get => _value40; set => Set(ref _value40, value);
    }
}

public sealed class TranscriptWord : ObservableObject
{
    private string _id = Guid.NewGuid().ToString("N");
    public string Id
    {
        get => _id; set => Set(ref _id, value);
    }
    private double _startTimeSeconds;
    public double StartTimeSeconds
    {
        get => _startTimeSeconds; set => Set(ref _startTimeSeconds, value);
    }
    private double _endTimeSeconds;
    public double EndTimeSeconds
    {
        get => _endTimeSeconds; set => Set(ref _endTimeSeconds, value);
    }
    private string _text = "";
    public string Text
    {
        get => _text; set => Set(ref _text, value);
    }
}

public sealed class TranscriptSettings : ObservableObject
{
    private bool _includeWordTimestamps;
    public bool IncludeWordTimestamps
    {
        get => _includeWordTimestamps; set => Set(ref _includeWordTimestamps, value);
    }
    private Dictionary<string, JsonElement>? _value46;
    [JsonExtensionData]
    public Dictionary<string, JsonElement>? Extensions
    {
        get => _value46; set => Set(ref _value46, value);
    }
}

public sealed class VideoProjectState : ObservableObject
{
    private int _schemaVersion = 1;
    public int SchemaVersion
    {
        get => _schemaVersion; set => Set(ref _schemaVersion, value);
    }
    private VideoSettings _exportSettings = new();
    public VideoSettings ExportSettings
    {
        get => _exportSettings; set => Set(ref _exportSettings, value);
    }
    private List<JsonElement> _compositions = [];
    public List<JsonElement> Compositions
    {
        get => _compositions; set => Set(ref _compositions, value);
    }
    private Dictionary<string, JsonElement>? _value50;
    [JsonExtensionData]
    public Dictionary<string, JsonElement>? Extensions
    {
        get => _value50; set => Set(ref _value50, value);
    }
}

public sealed class VideoSettings : ObservableObject
{
    private string _platform = "Instagram";
    public string Platform
    {
        get => _platform; set => Set(ref _platform, value);
    }
    private string _aspect = "Horizontal video (16:9)";
    public string Aspect
    {
        get => _aspect; set => Set(ref _aspect, value);
    }
    private int _width = 1920;
    public int Width
    {
        get => _width; set => Set(ref _width, value);
    }
    private int _height = 1080;
    public int Height
    {
        get => _height; set => Set(ref _height, value);
    }
    private string _codec = "h264";
    public string Codec
    {
        get => _codec; set => Set(ref _codec, value);
    }
    private string _encoding = "automatic";
    public string Encoding
    {
        get => _encoding; set => Set(ref _encoding, value);
    }
    private string _audioBitrate = "128k";
    public string AudioBitrate
    {
        get => _audioBitrate; set => Set(ref _audioBitrate, value);
    }
    private int _fps = 30;
    public int Fps
    {
        get => _fps; set => Set(ref _fps, value);
    }
    private bool _flipHorizontal;
    public bool FlipHorizontal
    {
        get => _flipHorizontal; set => Set(ref _flipHorizontal, value);
    }
    private bool _flipVertical;
    public bool FlipVertical
    {
        get => _flipVertical; set => Set(ref _flipVertical, value);
    }
    private string _previewQuality = "automatic";
    public string PreviewQuality
    {
        get => _previewQuality; set => Set(ref _previewQuality, value);
    }
    private List<string> _selectedChapterIds = [];
    public List<string> SelectedChapterIds
    {
        get => _selectedChapterIds; set => Set(ref _selectedChapterIds, value);
    }
    private bool _selectionInitialized;
    public bool SelectionInitialized
    {
        get => _selectionInitialized; set => Set(ref _selectionInitialized, value);
    }
    private Dictionary<string, JsonElement>? _value64;
    [JsonExtensionData]
    public Dictionary<string, JsonElement>? Extensions
    {
        get => _value64; set => Set(ref _value64, value);
    }
}

public sealed class VideoPreset : ObservableObject
{
    private string _platform = "";
    public string Platform
    {
        get => _platform; set => Set(ref _platform, value);
    }
    private string _aspect = "";
    public string Aspect
    {
        get => _aspect; set => Set(ref _aspect, value);
    }
    private int _width;
    public int Width
    {
        get => _width; set => Set(ref _width, value);
    }
    private int _height;
    public int Height
    {
        get => _height; set => Set(ref _height, value);
    }
    private int _fps;
    public int Fps
    {
        get => _fps; set => Set(ref _fps, value);
    }
    public override string ToString() => $"{Platform} — {Aspect} — {Width} × {Height}";
}

public sealed class ExportSettings : ObservableObject
{
    private string _outputFormat = "mp3";
    public string OutputFormat
    {
        get => _outputFormat; set => Set(ref _outputFormat, value);
    }
    private string _qualityPreset = "320k";
    public string QualityPreset
    {
        get => _qualityPreset; set => Set(ref _qualityPreset, value);
    }
    private string _encoder = "ffmpeg";
    public string Encoder
    {
        get => _encoder; set => Set(ref _encoder, value);
    }
    private int _channels = 2;
    public int Channels
    {
        get => _channels; set => Set(ref _channels, value);
    }
    private Dictionary<string, JsonElement>? _value74;
    [JsonExtensionData]
    public Dictionary<string, JsonElement>? Extensions
    {
        get => _value74; set => Set(ref _value74, value);
    }
}

public sealed class TranscriptionProvider : ObservableObject
{
    private string _id = "";
    public string Id
    {
        get => _id; set => Set(ref _id, value);
    }
    private string _name = "";
    public string Name
    {
        get => _name; set => Set(ref _name, value);
    }
    private string _detail = "";
    public string Detail
    {
        get => _detail; set => Set(ref _detail, value);
    }
    public override string ToString() => $"{Name} — {Detail}";
}

public sealed class TranscriptionModelInfo : ObservableObject
{
    private string _id = "";
    public string Id
    {
        get => _id; set => Set(ref _id, value);
    }
    private string _name = "";
    public string Name
    {
        get => _name; set => Set(ref _name, value);
    }
    private string _downloadSize = "";
    public string DownloadSize
    {
        get => _downloadSize; set => Set(ref _downloadSize, value);
    }
    private string _languages = "";
    public string Languages
    {
        get => _languages; set => Set(ref _languages, value);
    }
    private string _description = "";
    public string Description
    {
        get => _description; set => Set(ref _description, value);
    }
    private bool _installed;
    public bool Installed
    {
        get => _installed; set => Set(ref _installed, value);
    }
    private bool _downloadAllowed;
    public bool DownloadAllowed
    {
        get => _downloadAllowed; set => Set(ref _downloadAllowed, value);
    }
}
