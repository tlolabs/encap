using System.Diagnostics;
using System.Text.Json;

namespace EnCap;

internal sealed class EngineClient
{
    private readonly object processGate = new();
    private readonly HashSet<Process> currentProcesses = [];
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
        WriteIndented = true
    };
    private string EnginePath => Path.Combine(AppContext.BaseDirectory, "encap-engine.exe");

    public void CancelCurrentOperation()
    {
        lock (processGate)
        {
            foreach (var process in currentProcesses.ToArray())
                if (!process.HasExited) process.Kill(entireProcessTree: true);
        }
    }

    public Task<ProjectDocument> InspectAsync(string folder) => RunAsync<ProjectDocument>("inspect", folder);
    public Task<ProjectDocument> OpenAsync(string path) => RunAsync<ProjectDocument>("open", path);
    public Task<List<TranscriptionProvider>> ProvidersAsync() => RunAsync<List<TranscriptionProvider>>("providers");
    public Task<List<TranscriptionModelInfo>> ModelsAsync() => RunAsync<List<TranscriptionModelInfo>>("models");
    public Task<TranscriptionModelInfo> InstallModelAsync(string id) => RunAsync<TranscriptionModelInfo>("install-model", id);
    public Task<TranscriptionModelInfo> RemoveModelAsync(string id) => RunAsync<TranscriptionModelInfo>("remove-model", id);
    public async Task<string> SaveAsync(ProjectDocument project, string destination) => (await WithPayloadAsync<PathResponse>(project, "save", destination)).Path;
    public async Task<string> ExportAsync(ProjectDocument project, string destination) => (await WithPayloadAsync<PathResponse>(project, "export", destination)).Path;
    public Task<List<TranscriptSegment>> TranscribeAsync(ProjectDocument project, string provider) => WithPayloadAsync<List<TranscriptSegment>>(project, "transcribe", provider);
    public async Task<string> ExportTranscriptAsync(ProjectDocument project, string destination, string format) =>
        (await WithPayloadAsync<PathResponse>(project, "export-transcript", destination, format)).Path;
    public Task SaveRecoveryAsync(ProjectDocument project) => WithPayloadAsync<OkResponse>(project, "save-recovery");
    public async Task<ProjectDocument?> LoadRecoveryAsync() => (await RunAsync<RecoveryResponse>("load-recovery")).Project;
    public Task ClearRecoveryAsync() => RunAsync<OkResponse>("clear-recovery");

    private async Task<T> WithPayloadAsync<T>(ProjectDocument project, string command, params string[] arguments)
    {
        var payload = Path.Combine(Path.GetTempPath(), $"encap-{Guid.NewGuid():N}.json");
        try
        {
            await File.WriteAllTextAsync(payload, JsonSerializer.Serialize(project, JsonOptions));
            return await RunAsync<T>([command, payload, .. arguments]);
        }
        finally { try { File.Delete(payload); } catch { } }
    }

    private async Task<T> RunAsync<T>(params string[] arguments)
    {
        if (!File.Exists(EnginePath)) throw new InvalidOperationException("The EnCap engine is missing. Reinstall EnCap.");
        var start = new ProcessStartInfo(EnginePath) { UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true, CreateNoWindow = true };
        foreach (var argument in arguments) start.ArgumentList.Add(argument);
        using var process = new Process { StartInfo = start };
        process.Start();
        lock (processGate) currentProcesses.Add(process);
        try
        {
            var outputTask = process.StandardOutput.ReadToEndAsync();
            var errorTask = process.StandardError.ReadToEndAsync();
            await process.WaitForExitAsync();
            var output = await outputTask;
            var diagnostics = await errorTask;
            if (process.ExitCode != 0)
            {
                var failure = JsonSerializer.Deserialize<ErrorResponse>(output, JsonOptions);
                throw new InvalidOperationException(failure?.Error ?? (string.IsNullOrWhiteSpace(diagnostics) ? "The EnCap engine failed or was cancelled." : diagnostics.Trim()));
            }
            return JsonSerializer.Deserialize<T>(output, JsonOptions) ?? throw new InvalidOperationException("The EnCap engine returned an invalid response.");
        }
        finally
        {
            lock (processGate) currentProcesses.Remove(process);
        }
    }

    private sealed class PathResponse { public string Path { get; set; } = ""; }
    private sealed class RecoveryResponse { public ProjectDocument? Project { get; set; } }
    private sealed class OkResponse { public bool Ok { get; set; } }
    private sealed class ErrorResponse { public string Error { get; set; } = ""; }
}
