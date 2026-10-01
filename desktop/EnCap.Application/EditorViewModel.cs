using System.Collections.ObjectModel;
using System.ComponentModel;
namespace EnCap;

// Application coordination lives here; AXAML/code-behind only routes input and dialogs.
public sealed class EditorViewModel : ObservableObject, IDisposable
{
    private readonly IEngineClient engine;
    private readonly IUserDialogs dialogs;
    public IPlayback Playback
    {
        get;
    }
    private readonly List<INotifyPropertyChanged> observed = [];
    private CancellationTokenSource recovery = new();
    private CancellationTokenSource waveforms = new();
    private CancellationTokenSource previewCancellation = new();
    private readonly SemaphoreSlim recoveryGate = new(1, 1);
    private readonly List<AsyncCommand> commands = [];
    private bool presenting, disposed;
    private ProjectDocument? project;
    public ProjectDocument? Project
    {
        get => project; private set
        {
            Set(ref project, value);
            Changed(nameof(HasProject));
            RefreshCommands();
        }
    }
    public bool HasProject => Project is not null;
    private bool busy;
    public bool IsBusy
    {
        get => busy; private set
        {
            Set(ref busy, value);
            Changed(nameof(IsIdle));
            RefreshCommands();
        }
    }
    public bool IsIdle => !IsBusy;
    private bool dirty;
    public bool IsDirty
    {
        get => dirty; private set
        {
            Set(ref dirty, value);
            Changed(nameof(WindowTitle));
        }
    }
    public string WindowTitle => AppIdentity.Title + (Project is null ? "" : " — " + Project.Metadata.EpisodeTitle) + (IsDirty ? " *" : "");
    private string status = "Import an audio folder or open a project to begin.";
    public string Status
    {
        get => status; set => Set(ref status, value);
    }
    private bool error;
    public bool HasError
    {
        get => error; private set => Set(ref error, value);
    }
    private int mode;
    public int Mode
    {
        get => mode; private set
        {
            Set(ref mode, value);
            Changed(nameof(IsAudio));
            Changed(nameof(IsTranscript));
            Changed(nameof(IsVideo));
        }
    }
    public bool IsAudio => Mode == 0; public bool IsTranscript => Mode == 1; public bool IsVideo => Mode == 2;
    public ObservableCollection<SourceItem> Sources { get; } = [];
    public ObservableCollection<Chapter> Chapters { get; } = [];
    public ObservableCollection<TranscriptSegment> Segments { get; } = [];
    public ObservableCollection<VideoItem> VideoChapters { get; } = [];
    public ObservableCollection<TranscriptionProvider> Providers { get; } = [];
    public ObservableCollection<TranscriptionModelInfo> Models { get; } = [];
    public ObservableCollection<VideoPreset> Presets { get; } = [];
    public ObservableCollection<SourceItem> SelectedSources { get; } = [];
    public SourceItem? SelectedSource
    {
        get => SelectedSources.OrderBy(s => Sources.IndexOf(s)).FirstOrDefault();
        set
        {
            SelectedSources.Clear();
            if (value is not null)
                SelectedSources.Add(value);
            Changed(nameof(PlaybackDuration));
        }
    }
    private Chapter? selectedChapter;
    public Chapter? SelectedChapter
    {
        get => selectedChapter; set => Set(ref selectedChapter, value);
    }
    private VideoItem? selectedVideo;
    public VideoItem? SelectedVideo
    {
        get => selectedVideo; set => Set(ref selectedVideo, value);
    }
    private TranscriptionProvider? selectedProvider;
    public TranscriptionProvider? SelectedProvider
    {
        get => selectedProvider; set => Set(ref selectedProvider, value);
    }
    private TranscriptionModelInfo? selectedModel;
    public TranscriptionModelInfo? SelectedModel
    {
        get => selectedModel; set => Set(ref selectedModel, value);
    }
    private VideoPreset? preset;
    public VideoPreset? SelectedPreset
    {
        get => preset; set
        {
            if (Set(ref preset, value) && !presenting && value is not null && Project is not null)
            {
                var v = Project.Video.ExportSettings;
                v.Platform = value.Platform;
                v.Aspect = value.Aspect;
                v.Width = value.Width;
                v.Height = value.Height;
                v.Fps = value.Fps;
            }
        }
    }
    private ChapterNamingStyle naming = ChapterNaming.LoadPreference();
    public ChapterNamingStyle Naming
    {
        get => naming; set
        {
            if (Set(ref naming, value))
            {
                try
                {
                    ChapterNaming.SavePreference(value);
                }
                catch (Exception e) { Fail(e); }
            }
        }
    }
    public ChapterNamingStyle[] NamingStyles { get; } = Enum.GetValues<ChapterNamingStyle>();
    public string[] Formats { get; } = ["mp3", "aac"];
    public int[] Channels { get; } = [1, 2];
    public string[] Bitrates { get; } = ["64k", "96k", "128k", "160k", "192k", "256k", "320k"];
    public string[] Codecs { get; } = ["h264", "hevc"];
    public string[] Encodings { get; } = ["automatic", "hardware", "software"];
    public string[] PreviewQualities { get; } = ["automatic", "low", "medium", "high"];
    public string[] Themes { get; } = ["System", "Light", "Dark"];
    public AsyncCommand ImportCommand
    {
        get;
    }
    public AsyncCommand OpenCommand
    {
        get;
    }
    public AsyncCommand SaveCommand
    {
        get;
    }
    public AsyncCommand SaveAsCommand
    {
        get;
    }
    public AsyncCommand AddFilesCommand
    {
        get;
    }
    public AsyncCommand RemoveSourceCommand
    {
        get;
    }
    public AsyncCommand ArtworkCommand
    {
        get;
    }
    public AsyncCommand ChapterArtworkCommand
    {
        get;
    }
    public AsyncCommand ExportAudioCommand
    {
        get;
    }
    public AsyncCommand ExportVideoCommand
    {
        get;
    }
    public AsyncCommand ExportTextCommand
    {
        get;
    }
    public AsyncCommand ExportSrtCommand
    {
        get;
    }
    public AsyncCommand TranscribeCommand
    {
        get;
    }
    public AsyncCommand ModelsCommand
    {
        get;
    }
    public AsyncCommand InstallModelCommand
    {
        get;
    }
    public AsyncCommand RemoveModelCommand
    {
        get;
    }
    public AsyncCommand AddChapterCommand
    {
        get;
    }
    public AsyncCommand RemoveChapterCommand
    {
        get;
    }
    public AsyncCommand NameChaptersCommand
    {
        get;
    }
    public AsyncCommand AudioCommand
    {
        get;
    }
    public AsyncCommand TranscriptCommand
    {
        get;
    }
    public AsyncCommand VideoCommand
    {
        get;
    }
    public AsyncCommand PlayCommand
    {
        get;
    }
    public AsyncCommand PreviousCommand
    {
        get;
    }
    public AsyncCommand NextCommand
    {
        get;
    }
    public AsyncCommand SelectAllCommand
    {
        get;
    }
    public AsyncCommand SelectNoneCommand
    {
        get;
    }
    public AsyncCommand MoveUpCommand
    {
        get;
    }
    public AsyncCommand MoveDownCommand
    {
        get;
    }
    public AsyncCommand CancelCommand
    {
        get;
    }
    public EditorViewModel(IEngineClient engine, IUserDialogs dialogs, IPlayback playback)
    {
        SelectedSources.CollectionChanged += (_, _) => { Changed(nameof(SelectedSource)); Changed(nameof(PlaybackDuration)); };
        this.engine = engine;
        this.dialogs = dialogs;
        Playback = playback;
        AsyncCommand Command(Func<Task> action, bool needsProject = false)
        {
            var c = new AsyncCommand(async () => { try { await action(); } catch (Exception e) { Fail(e); } }, () => !IsBusy && (!needsProject || HasProject));
            commands.Add(c);
            return c;
        }
        AsyncCommand Sync(Action action, bool needsProject = true) => Command(() => { action(); return Task.CompletedTask; }, needsProject);
        ImportCommand = Command(ImportAsync);
        OpenCommand = Command(async () => { var paths = await dialogs.OpenAsync("Open EnCap project", ["encap"]); if (paths.Length > 0) await OpenPathAsync(paths[0]); });
        SaveCommand = Command(async () => { await SaveAsync(false); }, true);
        SaveAsCommand = Command(async () => { await SaveAsync(true); }, true);
        AddFilesCommand = Command(async () => await AddFilesAsync(await dialogs.OpenAsync("Add recordings", ["wav", "wave", "aif", "aiff", "aifc"], true)), true);
        RemoveSourceCommand = Command(async () => { if (SelectedSource is not null) await RemoveSourcesAsync([SelectedSource.Source]); }, true);
        ArtworkCommand = Command(async () => await ArtworkAsync(null), true);
        ChapterArtworkCommand = Command(async () => { if (SelectedChapter is not null) await ArtworkAsync(SelectedChapter); }, true);
        ExportAudioCommand = Command(async () => await ExportAsync("audio"), true);
        ExportVideoCommand = Command(async () => await ExportAsync("video"), true);
        ExportTextCommand = Command(async () => await ExportAsync("txt"), true);
        ExportSrtCommand = Command(async () => await ExportAsync("srt"), true);
        TranscribeCommand = Command(TranscribeAsync, true);
        ModelsCommand = Command(LoadModelsAsync);
        InstallModelCommand = Command(async () => await ChangeModelAsync(false));
        RemoveModelCommand = Command(async () => await ChangeModelAsync(true));
        AddChapterCommand = Sync(AddChapter);
        RemoveChapterCommand = Sync(RemoveChapter);
        NameChaptersCommand = Sync(() => { presenting = true; try { ChapterNaming.Apply(Project!, Naming); RebuildRows(); } finally { presenting = false; } MarkDirty(); });
        AudioCommand = Command(async () => await SwitchModeAsync(0));
        TranscriptCommand = Command(async () => await SwitchModeAsync(1));
        VideoCommand = Command(async () => await SwitchModeAsync(2));
        PlayCommand = Command(TogglePlaybackAsync, true);
        PreviousCommand = Command(async () => await AdjacentAsync(-1), true);
        NextCommand = Command(async () => await AdjacentAsync(1), true);
        SelectAllCommand = Sync(() => SelectVideo(true));
        SelectNoneCommand = Sync(() => SelectVideo(false));
        MoveUpCommand = Sync(() => MoveVideo(-1));
        MoveDownCommand = Sync(() => MoveVideo(1));
        CancelCommand = new AsyncCommand(() => { Status = "Cancelling safely…"; previewCancellation.Cancel(); engine.CancelCurrentOperation(); return Task.CompletedTask; }, () => IsBusy);
        commands.Add(CancelCommand);
    }
    private void RefreshCommands()
    {
        foreach (var c in commands)
            c.Refresh();
    }
    public void Fail(Exception e)
    {
        HasError = true;
        Status = e.Message;
    }
    private async Task WorkAsync(string message, Func<Task> action)
    {
        if (IsBusy)
            return;
        IsBusy = true;
        HasError = false;
        Status = message;
        try
        {
            await recoveryGate.WaitAsync();
            try
            {
                await action();
            }
            finally { recoveryGate.Release(); }
        }
        finally { IsBusy = false; }
    }
    public async Task InitializeAsync()
    {
        try
        {
            await WorkAsync("Loading local engines and recovery…", async () =>
            {
                foreach (var provider in await engine.ProvidersAsync())
                    Providers.Add(provider);
                SelectedProvider = Providers.FirstOrDefault();
                foreach (var preset in await engine.VideoPresetsAsync())
                    Presets.Add(preset);
                var restored = await engine.LoadRecoveryAsync();
                if (restored is not null)
                {
                    Present(restored, true);
                    Status = "Recovered unsaved work from the previous session.";
                }
                else
                    Status = "Import an audio folder or open a project to begin.";
            });
        }
        catch (Exception error) { Fail(error); }
    }
    public void Present(ProjectDocument document, bool changed = false)
    {
        Playback.Stop();
        videoPlaying = false;
        playingPath = null;
        previewIndex = 0;
        CancelRecovery();
        waveforms.Cancel();
        waveforms.Dispose();
        waveforms = new();
        foreach (var o in observed)
            o.PropertyChanged -= ModelChanged;
        observed.Clear();
        presenting = true;
        Project = document;
        Mode = Array.IndexOf(new[] { "audio", "transcript", "video" }, document.ActiveMode);
        if (Mode < 0)
            Mode = 0;
        RebuildRows();
        Observe(document);
        Observe(document.Metadata);
        Observe(document.ExportSettings);
        Observe(document.TranscriptSettings);
        Observe(document.Video.ExportSettings);
        SelectedPreset = Presets.FirstOrDefault(p => p.Platform == document.Video.ExportSettings.Platform && p.Width == document.Video.ExportSettings.Width && p.Height == document.Video.ExportSettings.Height);
        PreviewArtwork=VideoChapters.FirstOrDefault(c=>c.Selected)?.Chapter.ImagePath??document.Metadata.ArtworkPath;
        foreach(var property in new[]{nameof(PreviewWidth),nameof(PreviewHeight),nameof(FlipX),nameof(FlipY),nameof(PlaybackDuration)})Changed(property);
        presenting = false;
        IsDirty = changed;
        Status = $"Loaded {Sources.Count} recordings.";
        Changed(nameof(WindowTitle));
        _ = LoadWaveformsAsync(waveforms.Token);
        if (changed)
            MarkDirty();
    }
    private void Observe(INotifyPropertyChanged value)
    {
        if (observed.Contains(value))
            return;
        observed.Add(value);
        value.PropertyChanged += ModelChanged;
    }
    private void ModelChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (presenting)
            return;
        if (sender is ExportSettings settings && e.PropertyName == nameof(ExportSettings.OutputFormat))
            settings.Encoder = "ffmpeg";
        if (sender is Chapter && e.PropertyName == nameof(Chapter.Title))
            Naming = ChapterNamingStyle.Custom;
        if (sender is Chapter && e.PropertyName == nameof(Chapter.DurationSeconds) && Project is not null)
        {
            presenting = true;
            double start = 0;
            foreach (var chapter in Project.Chapters)
            {
                chapter.StartTimeSeconds = start;
                start += chapter.DurationSeconds;
            }
            presenting = false;
            SyncVideo();
        }
        MarkDirty();
        Changed(nameof(WindowTitle));
        if (sender is VideoSettings)
        {
            Changed(nameof(PreviewWidth));
            Changed(nameof(PreviewHeight));
            Changed(nameof(FlipX));
            Changed(nameof(FlipY));
        }
    }
    private void RebuildRows()
    {
        if (Project is null)
            return;
        var selectedPath = SelectedSource?.Source.SourcePath;
        Sources.Clear();
        foreach (var s in Project.AudioSources)
            Sources.Add(new(s));
        SelectedSource = Sources.FirstOrDefault(s => s.Source.SourcePath == selectedPath);
        Chapters.Clear();
        int n = 1;
        foreach (var c in Project.Chapters)
        {
            c.DisplayNumber = n++;
            Chapters.Add(c);
            Observe(c);
        }
        Segments.Clear();
        foreach (var s in Project.TranscriptSegments)
        {
            Segments.Add(s);
            Observe(s);
        }
        VideoChapters.Clear();
        var selected = Project.Video.ExportSettings.SelectedChapterIds;
        var ordered = selected.Select(id => Project.Chapters.FirstOrDefault(c => c.Id == id)).OfType<Chapter>().ToList();
        ordered.AddRange(Project.Chapters.Where(c => !ordered.Contains(c)));
        foreach (var c in ordered)
        {
            var item = new VideoItem(c, !Project.Video.ExportSettings.SelectionInitialized || selected.Contains(c.Id));
            item.PropertyChanged += (_, _) => { SyncVideo(); MarkDirty(); };
            VideoChapters.Add(item);
        }
        SyncVideo();
    }
    public void MarkDirty()
    {
        if (presenting || Project is null || disposed)
            return;
        IsDirty = true;
        CancelRecovery();
        var token = recovery.Token;
        _ = RecoverLaterAsync(token);
    }
    private void CancelRecovery()
    {
        recovery.Cancel();
        recovery.Dispose();
        recovery = new();
    }
    private async Task RecoverLaterAsync(CancellationToken token)
    {
        try
        {
            await Task.Delay(1000, token);
            await recoveryGate.WaitAsync(token);
            try
            {
                if (!token.IsCancellationRequested && Project is not null && IsDirty)
                    await engine.SaveRecoveryAsync(Project);
            }
            finally { recoveryGate.Release(); }
        }
        catch (OperationCanceledException) { }
        catch (Exception e) { Fail(e); }
    }
    public async Task<bool> ConfirmReplaceAsync()
    {
        if (IsBusy)
            return false;
        if (!IsDirty)
            return true;
        return await dialogs.UnsavedAsync() switch
        {
            SaveChoice.Save => await SaveAsync(false),
            SaveChoice.Discard => true,
            _ => false
        };
    }
    public async Task<bool> CanCloseAsync()
    {
        if (!await ConfirmReplaceAsync())
            return false;
        CancelRecovery();
        await recoveryGate.WaitAsync();
        try
        {
            await engine.ClearRecoveryAsync();
        }
        finally { recoveryGate.Release(); }
        Playback.Stop();
        return true;
    }
    private async Task ImportAsync()
    {
        if (!await ConfirmReplaceAsync())
            return;
        var folder = await dialogs.FolderAsync();
        if (folder is null)
            return;
        await WorkAsync("Reading recordings…", async () => { var next = await engine.InspectAsync(folder); ChapterNaming.Apply(next, Naming); Present(next, true); });
    }
    public async Task OpenPathAsync(string path)
    {
        if (!await ConfirmReplaceAsync())
            return;
        await WorkAsync("Opening project…", async () => { var next = await engine.OpenAsync(path); await engine.ClearRecoveryAsync(); Present(next); });
    }
    public async Task AddFilesAsync(string[] files)
    {
        if (Project is null || files.Length == 0 || IsBusy)
            return;
        await WorkAsync("Adding recordings…", async () => { var previous = Project.Chapters.Select(c => c.Id).ToHashSet(); var next = await engine.EditAudioAsync(Project, files, []); ChapterNaming.Apply(next, Naming, next.Chapters.Where(c => !previous.Contains(c.Id)).Select(c => c.Id).ToHashSet()); Present(next, true); });
    }
    public async Task RemoveSourcesAsync(IReadOnlyList<AudioSource> sources)
    {
        if (Project is null || sources.Count == 0 || IsBusy)
            return;
        if (!await dialogs.ConfirmAsync("Remove recordings?", "Remove these recordings and their chapters from the project? Original files stay on disk."))
            return;
        Playback.Stop();
        await WorkAsync("Removing recordings…", async () => Present(await engine.EditAudioAsync(Project, [], sources.Select(s => s.SourcePath).ToArray()), true));
    }
    public async Task<bool> SaveAsync(bool saveAs)
    {
        if (Project is null || IsBusy)
            return false;
        var path = saveAs ? null : Project.ProjectPath;
        path ??= await dialogs.SaveAsync("Save EnCap project", "encap", Project.Metadata.EpisodeTitle);
        if (path is null)
            return false;
        var saved = false;
        await WorkAsync("Saving project…", async () => { Project.ProjectPath = await engine.SaveAsync(Project, path); CancelRecovery(); await engine.ClearRecoveryAsync(); IsDirty = false; saved = true; Status = "Project saved."; });
        return saved;
    }
    private async Task<bool> ConfirmModeChangeAsync()
    {
        if (!IsDirty)
            return true;
        return await dialogs.UnsavedAsync(false) switch
        {
            SaveChoice.Save => await SaveAsync(false),
            SaveChoice.Discard => true,
            _ => false
        };
    }
    public async Task SwitchModeAsync(int next)
    {
        if (next is < 0 or > 2 || IsBusy || next == Mode)
            return;
        Playback.Stop();
        videoPlaying = false;
        playingPath = null;
        if (Project is null)
        {
            Mode = next;
            return;
        }
        var old = Project.ActiveMode;
        Project.ActiveMode = new[] { "audio", "transcript", "video" }[next];
        try
        {
            if (!string.IsNullOrEmpty(Project.ProjectPath))
            {
                if (!await SaveAsync(false))
                {
                    Project.ActiveMode = old;
                    return;
                }
            }
            else if (!await ConfirmModeChangeAsync())
            {
                Project.ActiveMode = old;
                return;
            }
            Mode = next;
            PreviewArtwork = VideoChapters.FirstOrDefault(c => c.Selected)?.Chapter.ImagePath ?? Project.Metadata.ArtworkPath;
        }
        catch { Project.ActiveMode = old; throw; }
    }
    private async Task ArtworkAsync(Chapter? chapter)
    {
        var files = await dialogs.OpenAsync("Choose artwork", ["png", "jpg", "jpeg", "webp", "tif", "tiff"]);
        if (files.Length == 0 || Project is null)
            return;
        if (chapter is null)
            Project.Metadata.ArtworkPath = files[0];
        else
            chapter.ImagePath = files[0];
        Changed(nameof(ArtworkPath));
    }
    public string? ArtworkPath => Project?.Metadata.ArtworkPath;
    private void AddChapter()
    {
        if (Project is null)
            return;
        var duration = Project.Chapters.Sum(c => c.DurationSeconds);
        var source = 1;
        double end = 0;
        for (int i = 0; i < Project.AudioSources.Count; i++)
        {
            end += Project.AudioSources[i].DurationSeconds;
            if (duration < end)
            {
                source = i + 1;
                break;
            }
        }
        Project.Chapters.Add(new()
        {
            Title = $"Chapter {Project.Chapters.Count + 1}",
            ChapterNumber = source,
            StartTimeSeconds = duration,
            DurationSeconds = 30
        });
        RebuildRows();
        MarkDirty();
    }
    private void RemoveChapter()
    {
        if (Project is null || SelectedChapter is null)
            return;
        Project.Chapters.Remove(SelectedChapter);
        double start = 0;
        foreach (var c in Project.Chapters)
        {
            c.StartTimeSeconds = start;
            start += c.DurationSeconds;
        }
        RebuildRows();
        MarkDirty();
    }
    private async Task ExportAsync(string kind)
    {
        if (Project is null)
            return;
        SyncVideo();
        if (kind == "video" && (!VideoChapters.Any(c => c.Selected) || Project.Metadata.ArtworkPath is null))
            throw new InvalidOperationException("Select chapters and add episode artwork before exporting video.");
        var extension = kind switch
        {
            "audio" => Project.ExportSettings.OutputFormat == "aac" ? "m4a" : "mp3",
            "video" => "mp4",
            _ => kind
        };
        var path = await dialogs.SaveAsync("Export " + kind, extension, Project.Metadata.EpisodeTitle);
        if (path is null)
            return;
        await WorkAsync("Exporting " + kind + "…", async () => { var output = kind switch { "audio" => await engine.ExportAsync(Project, path), "video" => await engine.ExportVideoAsync(Project, path), _ => await engine.ExportTranscriptAsync(Project, path, kind) }; Status = "Exported " + Path.GetFileName(output) + "."; });
    }
    private async Task TranscribeAsync()
    {
        if (Project is null || SelectedProvider is null)
            return;
        await WorkAsync("Transcribing locally…", async () => { Project.TranscriptSegments = await engine.TranscribeAsync(Project, SelectedProvider.Id); RebuildRows(); MarkDirty(); });
    }
    private async Task LoadModelsAsync()
    {
        await WorkAsync("Loading local models…", async () => { Models.Clear(); foreach (var m in await engine.ModelsAsync()) Models.Add(m); Status = "Select a model to download or remove."; });
    }
    private async Task ChangeModelAsync(bool remove)
    {
        if (SelectedModel is null)
            return;
        var m = SelectedModel;
        if (!remove && !m.DownloadAllowed)
            throw new InvalidOperationException("This compatible model is managed by another application.");
        await WorkAsync(remove ? "Removing model…" : "Downloading and verifying model…", async () => { if (remove) await engine.RemoveModelAsync(m.Id); else await engine.InstallModelAsync(m.Id); Providers.Clear(); foreach (var p in await engine.ProvidersAsync()) Providers.Add(p); SelectedProvider = Providers.FirstOrDefault(); });
        await LoadModelsAsync();
    }
    private void SyncVideo()
    {
        if (Project is null)
            return;
        var v = Project.Video.ExportSettings;
        var wasPresenting = presenting;
        presenting = true;
        v.SelectedChapterIds = VideoChapters.Where(c => c.Selected).Select(c => c.Chapter.Id).ToList();
        v.SelectionInitialized = true;
        double start = 0;
        foreach (var c in VideoChapters.Where(c => c.Selected))
        {
            c.StartSeconds = start;
            start += c.Chapter.DurationSeconds;
        }
        presenting = wasPresenting;
        Changed(nameof(VideoDuration));
    }
    public double VideoDuration => VideoChapters.Where(c => c.Selected).Sum(c => c.Chapter.DurationSeconds);
    private void SelectVideo(bool selected)
    {
        foreach (var c in VideoChapters)
            c.Selected = selected;
        SyncVideo();
        MarkDirty();
    }
    public void MoveVideo(int delta)
    {
        if (SelectedVideo is null)
            return;
        var index = VideoChapters.IndexOf(SelectedVideo);
        var next = index + delta;
        if (next < 0 || next >= VideoChapters.Count)
            return;
        VideoChapters.Move(index, next);
        SyncVideo();
        MarkDirty();
    }
    public void ReorderVideo(VideoItem item, int destination)
    {
        var old = VideoChapters.IndexOf(item);
        if (old < 0 || destination < 0 || destination >= VideoChapters.Count)
            return;
        VideoChapters.Move(old, destination);
        SyncVideo();
        MarkDirty();
    }
    private async Task LoadWaveformsAsync(CancellationToken token)
    {
        try
        {
            foreach (var item in Sources.ToArray())
            {
                token.ThrowIfCancellationRequested();
                item.Peaks = await engine.WaveformAsync(item.Source.SourcePath, token);
            }
        }
        catch (OperationCanceledException) { }
        catch (Exception e) { if (!token.IsCancellationRequested) Fail(e); }
    }
    private int previewIndex;
    private bool videoPlaying;
    private double playbackPosition;
    public double PlaybackPosition
    {
        get => playbackPosition; private set
        {
            Set(ref playbackPosition, value);
            Changed(nameof(PlaybackTime));
        }
    }
    public double PlaybackDuration => IsVideo ? VideoDuration : Sources.FirstOrDefault(s => s.Source.SourcePath == playingPath)?.Source.DurationSeconds ?? SelectedSource?.Source.DurationSeconds ?? 1;
    public string MediaTitle => IsVideo ? VideoChapters.Where(c => c.Selected).ElementAtOrDefault(previewIndex)?.Chapter.Title ?? "EnCap" : Sources.FirstOrDefault(s => s.Source.SourcePath == playingPath)?.Name ?? "EnCap";
    public string PlaybackTime => $"{TimeSpan.FromSeconds(Math.Max(0, PlaybackPosition)):hh\\:mm\\:ss} / {TimeSpan.FromSeconds(Math.Max(0, PlaybackDuration)):hh\\:mm\\:ss}";
    public string PlaybackLabel => Playback.IsPlaying ? "Pause" : "Play";
    private string? previewArtwork;
    public string? PreviewArtwork
    {
        get => previewArtwork; private set => Set(ref previewArtwork, value);
    }
    public double PreviewWidth => Math.Min(520, 360 * (double)(Project?.Video.ExportSettings.Width ?? 1920) / Math.Max(1, Project?.Video.ExportSettings.Height ?? 1080));
    public double PreviewHeight => PreviewWidth * Math.Max(1, Project?.Video.ExportSettings.Height ?? 1080) / Math.Max(1, Project?.Video.ExportSettings.Width ?? 1920);
    public double FlipX => Project?.Video.ExportSettings.FlipHorizontal == true ? -1 : 1; public double FlipY => Project?.Video.ExportSettings.FlipVertical == true ? -1 : 1;
    private string? playingPath;
    private async Task OpenPlaybackAsync(string path)
    {
        previewCancellation.Dispose();
        previewCancellation = new();
        await WorkAsync("Opening recording preview…", () => Playback.OpenAsync(path, previewCancellation.Token));
        Status="Recording preview ready.";
    }
    public async Task TogglePlaybackAsync()
    {
        if (Playback.IsPlaying && (IsVideo || playingPath == SelectedSource?.Source.SourcePath))
        {
            Playback.Pause();
            videoPlaying = false;
        }
        else if (IsVideo)
        {
            if (playingPath is null)
                await LoadVideoAsync(previewIndex, 0, true);
            else
            {
                Playback.Play();
                videoPlaying = true;
            }
        }
        else if (SelectedSource is not null)
        {
            if (playingPath != SelectedSource.Source.SourcePath)
            {
                await OpenPlaybackAsync(SelectedSource.Source.SourcePath);
                playingPath = SelectedSource.Source.SourcePath;
            }
            Playback.Play();
        }
        Changed(nameof(PlaybackLabel));
        Changed(nameof(PlaybackDuration));
    }
    public async Task ShuttleAsync(int direction, bool slow = false)
    {
        if (SelectedSource is null || IsBusy || !IsAudio)
            return;
        if (playingPath != SelectedSource.Source.SourcePath)
        {
            await OpenPlaybackAsync(SelectedSource.Source.SourcePath);
            playingPath = SelectedSource.Source.SourcePath;
        }
        Playback.Play(SourceShuttle.Rate(Playback.Rate, direction, slow));
        Changed(nameof(PlaybackLabel));
    }
    public void Pause()
    {
        videoPlaying = false;
        Playback.Pause();
        Changed(nameof(PlaybackLabel));
    }
    public async Task SeekAsync(double position)
    {
        if (IsVideo)
        {
            var selected = VideoChapters.Where(c => c.Selected).ToList();
            var index = selected.FindLastIndex(c => c.StartSeconds <= position);
            if (index >= 0)
                await LoadVideoAsync(index, position - selected[index].StartSeconds, Playback.IsPlaying);
        }
        else
            Playback.Seek(position);
        Tick();
    }
    public async Task AdjacentAsync(int delta)
    {
        if (IsVideo)
            await LoadVideoAsync(previewIndex + delta, 0, true);
        else
        {
            var next = Math.Clamp((SelectedSource is null ? -1 : Sources.IndexOf(SelectedSource)) + delta, 0, Math.Max(0, Sources.Count - 1));
            if (Sources.Count == 0)
                return;
            Playback.Stop();
            playingPath = null;
            SelectedSource = Sources[next];
            Changed(nameof(SelectedSource));
            await TogglePlaybackAsync();
        }
    }
    public async Task PreviewChapterAsync()
    {
        if (SelectedVideo is null)
            return;
        await LoadVideoAsync(VideoChapters.Where(c => c.Selected).ToList().IndexOf(SelectedVideo), 0, false);
    }
    private async Task LoadVideoAsync(int index, double within, bool play)
    {
        if (Project is null)
            return;
        var selected = VideoChapters.Where(c => c.Selected).ToList();
        if (selected.Count == 0)
        {
            Playback.Stop();
            return;
        }
        previewIndex = Math.Clamp(index, 0, selected.Count - 1);
        var c = selected[previewIndex].Chapter;
        var source = c.ChapterNumber - 1;
        if (source < 0 || source >= Sources.Count)
            throw new InvalidOperationException("Chapter refers to a missing recording.");
        var path = Sources[source].Source.SourcePath;
        await OpenPlaybackAsync(path);
        playingPath = path;
        Playback.Seek(within);
        PreviewArtwork = c.ImagePath ?? Project.Metadata.ArtworkPath;
        videoPlaying = play;
        if (play)
            Playback.Play();
        Changed(nameof(PlaybackLabel));
        Changed(nameof(PlaybackDuration));
        Tick();
    }
    public void Tick()
    {
        var selected = VideoChapters.Where(c => c.Selected).ToList();
        if (IsVideo && previewIndex < selected.Count)
        {
            var c = selected[previewIndex];
            PlaybackPosition = c.StartSeconds + Math.Min(Playback.Position, c.Chapter.DurationSeconds);
            if (videoPlaying && (Playback.Position >= c.Chapter.DurationSeconds || (!Playback.IsPlaying && Playback.Position > 0)))
            {
                videoPlaying = false;
                Playback.Pause();
                if (previewIndex + 1 < selected.Count)
                    _ = NextCommand.ExecuteAsync();
            }
        }
        else
            PlaybackPosition = Playback.Position;
        Changed(nameof(PlaybackLabel));
    }
    public void Dispose()
    {
        disposed = true;
        CancelRecovery();
        recovery.Cancel();
        waveforms.Cancel();
        foreach (var o in observed)
            o.PropertyChanged -= ModelChanged;
        previewCancellation.Cancel();
        Playback.Dispose();
    }
}
public sealed class SourceItem(AudioSource source) : ObservableObject
{
    public override string ToString() => Name; public AudioSource Source { get; } = source; public string Name => Source.DisplayName; public string Detail => $"{Path.GetExtension(Source.SourcePath).TrimStart('.').ToUpperInvariant()} · {TimeSpan.FromSeconds(Source.DurationSeconds):hh\\:mm\\:ss}"; private double[] peaks = []; public double[] Peaks
    {
        get => peaks; set => Set(ref peaks, value);
    }
}
public sealed class VideoItem(Chapter chapter, bool selected) : ObservableObject
{
    public override string ToString() => Chapter.Title; public Chapter Chapter { get; } = chapter; private bool selectedValue = selected; public bool Selected
    {
        get => selectedValue; set => Set(ref selectedValue, value);
    }
    public double StartSeconds
    {
        get; set;
    }
}
