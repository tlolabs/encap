namespace EnCap;

public interface IEngineClient
{
    bool IsBusy
    {
        get;
    }
    void CancelCurrentOperation();
    Task<double[]> WaveformAsync(string path, CancellationToken token);
    Task<ProjectDocument> InspectAsync(string folder);
    Task<ProjectDocument> OpenAsync(string path);
    Task<ProjectDocument> EditAudioAsync(ProjectDocument project, IReadOnlyList<string> add, IReadOnlyList<string> remove);
    Task<string> SaveAsync(ProjectDocument project, string path);
    Task<string> ExportAsync(ProjectDocument project, string path);
    Task<string> ExportVideoAsync(ProjectDocument project, string path);
    Task<string> ExportTranscriptAsync(ProjectDocument project, string path, string format);
    Task<List<TranscriptionProvider>> ProvidersAsync();
    Task<List<TranscriptionModelInfo>> ModelsAsync();
    Task<TranscriptionModelInfo> InstallModelAsync(string id);
    Task<TranscriptionModelInfo> RemoveModelAsync(string id);
    Task<List<TranscriptSegment>> TranscribeAsync(ProjectDocument project, string provider);
    Task<List<VideoPreset>> VideoPresetsAsync();
    Task SaveRecoveryAsync(ProjectDocument project);
    Task<ProjectDocument?> LoadRecoveryAsync();
    Task ClearRecoveryAsync();
}
public enum SaveChoice
{
    Save, Discard, Cancel
}
public interface IUserDialogs
{
    Task<string?> FolderAsync();
    Task<string[]> OpenAsync(string title, string[] extensions, bool multiple = false);
    Task<string?> SaveAsync(string title, string extension, string suggestedName);
    Task<bool> ConfirmAsync(string title, string message);
    Task<SaveChoice> UnsavedAsync(bool replacing = true);
}
public interface IPlayback : IDisposable
{
    double Position
    {
        get;
    }
    double Rate
    {
        get;
    }
    double Volume
    {
        get; set;
    }
    bool IsPlaying
    {
        get;
    }
    Task OpenAsync(string path, CancellationToken cancellationToken = default);
    void Play(double rate = 1);
    void Pause();
    void Seek(double seconds);
    void Stop();
}
