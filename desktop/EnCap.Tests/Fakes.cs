using EnCap;
namespace EnCap.Tests;

internal sealed class FakeDialogs : IUserDialogs
{
    public string? Folder = "/recordings", Destination = "/saved.encap";
    public string[] Files = [];
    public SaveChoice Choice = SaveChoice.Cancel;
    public bool Confirm = true;
    public Task<string?> FolderAsync() => Task.FromResult(Folder);
    public Task<string[]> OpenAsync(string title, string[] extensions, bool multiple = false) => Task.FromResult(Files);
    public Task<string?> SaveAsync(string title, string extension, string suggestedName) => Task.FromResult(Destination);
    public Task<bool> ConfirmAsync(string title, string message) => Task.FromResult(Confirm);
    public Task<SaveChoice> UnsavedAsync(bool replacing = true) => Task.FromResult(Choice);
}
internal sealed class FakePlayback : IPlayback
{
    public double Volume { get; set; } = 1; public double Position
    {
        get; private set;
    }
    public double Rate { get; private set; } = 1;
    public bool IsPlaying
    {
        get; private set;
    }
    public int Opens; public string? Path;
    public Task OpenAsync(string path, CancellationToken token = default)
    {
        Opens++;
        Path = path;
        Position = 0;
        IsPlaying = false;
        return Task.CompletedTask;
    }
    public void Play(double rate = 1)
    {
        Rate = rate;
        IsPlaying = true;
    }
    public void Pause() => IsPlaying = false;
    public void Seek(double seconds) => Position = seconds;
    public void Stop()
    {
        Path = null;
        Position = 0;
        IsPlaying = false;
    }
    public void Dispose() => Stop();
}
internal sealed class FakeEngine : IEngineClient
{
    public bool IsBusy => false; public bool Cancelled, ThrowSave; public int Saved, Recovered, Cleared;
    public string? ExportKind; public TaskCompletionSource<string>? PendingExport;
    public ProjectDocument Document = Fixture();
    public static ProjectDocument Fixture() => new() { Metadata = new() { EpisodeTitle = "Episode", ArtworkPath = "/cover.png" }, AudioSources = [new() { SourcePath = "/one.wav", DisplayName = "One", DurationSeconds = 10 }, new() { SourcePath = "/two.aiff", DisplayName = "Two", DurationSeconds = 20 }], Chapters = [new() { Id = "a", Title = "One", ChapterNumber = 1, DurationSeconds = 10 }, new() { Id = "b", Title = "Two", ChapterNumber = 2, StartTimeSeconds = 10, DurationSeconds = 20 }] };
    public void CancelCurrentOperation()
    {
        Cancelled = true;
        PendingExport?.TrySetCanceled();
    }
    public Task<double[]> WaveformAsync(string path, CancellationToken token) => Task.FromResult(new[] { 0.2, 0.5 });
    public Task<ProjectDocument> InspectAsync(string folder) => Task.FromResult(Document);
    public Task<ProjectDocument> OpenAsync(string path) => Task.FromResult(Document);
    public Task<ProjectDocument> EditAudioAsync(ProjectDocument project, IReadOnlyList<string> add, IReadOnlyList<string> remove)
    {
        foreach (var file in add)
            project.AudioSources.Add(new()
            {
                SourcePath = file,
                DisplayName = file
            });
        project.AudioSources.RemoveAll(s => remove.Contains(s.SourcePath));
        return Task.FromResult(project);
    }
    public Task<string> SaveAsync(ProjectDocument project, string path)
    {
        if (ThrowSave)
            throw new IOException("Disk full");
        Saved++;
        return Task.FromResult(path);
    }
    public Task<string> ExportAsync(ProjectDocument project, string path)
    {
        ExportKind = "audio";
        return PendingExport?.Task ?? Task.FromResult(path);
    }
    public Task<string> ExportVideoAsync(ProjectDocument project, string path)
    {
        ExportKind = "video";
        return Task.FromResult(path);
    }
    public Task<string> ExportTranscriptAsync(ProjectDocument project, string path, string format)
    {
        ExportKind = format;
        return Task.FromResult(path);
    }
    public Task<List<TranscriptionProvider>> ProvidersAsync() => Task.FromResult(new List<TranscriptionProvider> { new() { Id = "whisper", Name = "Whisper" } });
    public Task<List<TranscriptionModelInfo>> ModelsAsync() => Task.FromResult(new List<TranscriptionModelInfo> { new() { Id = "tiny", DownloadAllowed = true } });
    public Task<TranscriptionModelInfo> InstallModelAsync(string id) => Task.FromResult(new TranscriptionModelInfo { Id = id, Installed = true });
    public Task<TranscriptionModelInfo> RemoveModelAsync(string id) => Task.FromResult(new TranscriptionModelInfo { Id = id });
    public Task<List<TranscriptSegment>> TranscribeAsync(ProjectDocument project, string provider) => Task.FromResult(new List<TranscriptSegment> { new() { Text = "Recognized speech", Speaker = "Speaker" } });
    public Task<List<VideoPreset>> VideoPresetsAsync() => Task.FromResult(new List<VideoPreset> { new() { Platform = "Instagram", Aspect = "Portrait", Width = 1080, Height = 1920, Fps = 30 } });
    public Task SaveRecoveryAsync(ProjectDocument project)
    {
        Recovered++;
        return Task.CompletedTask;
    }
    public Task<ProjectDocument?> LoadRecoveryAsync() => Task.FromResult<ProjectDocument?>(null);
    public Task ClearRecoveryAsync()
    {
        Cleared++;
        return Task.CompletedTask;
    }
}
