using System.Diagnostics;
using System.Text.Json;

namespace EnCap;

internal sealed class EngineClient
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
        WriteIndented = true
    };
    private string EnginePath => Path.Combine(AppContext.BaseDirectory, "encap-engine.exe");

    public Task<ProjectDocument> InspectAsync(string folder) => RunAsync<ProjectDocument>("inspect", folder);
    public Task<ProjectDocument> OpenAsync(string path) => RunAsync<ProjectDocument>("open", path);
    public Task<List<TranscriptionProvider>> ProvidersAsync() => RunAsync<List<TranscriptionProvider>>("providers");
    public async Task<string> SaveAsync(ProjectDocument project, string destination) => (await WithPayloadAsync<PathResponse>(project, "save", destination)).Path;
    public async Task<string> ExportAsync(ProjectDocument project, string destination) => (await WithPayloadAsync<PathResponse>(project, "export", destination)).Path;
    public Task<List<TranscriptSegment>> TranscribeAsync(ProjectDocument project, string provider) => WithPayloadAsync<List<TranscriptSegment>>(project, "transcribe", provider);

    private async Task<T> WithPayloadAsync<T>(ProjectDocument project, string command, string argument)
    {
        var payload = Path.Combine(Path.GetTempPath(), $"encap-{Guid.NewGuid():N}.json");
        try
        {
            await File.WriteAllTextAsync(payload, JsonSerializer.Serialize(project, JsonOptions));
            return await RunAsync<T>(command, payload, argument);
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
        var outputTask = process.StandardOutput.ReadToEndAsync();
        var errorTask = process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync();
        var output = await outputTask;
        var diagnostics = await errorTask;
        if (process.ExitCode != 0)
        {
            var failure = JsonSerializer.Deserialize<ErrorResponse>(output, JsonOptions);
            throw new InvalidOperationException(failure?.Error ?? (string.IsNullOrWhiteSpace(diagnostics) ? "The EnCap engine failed." : diagnostics.Trim()));
        }
        return JsonSerializer.Deserialize<T>(output, JsonOptions) ?? throw new InvalidOperationException("The EnCap engine returned an invalid response.");
    }

    private sealed class PathResponse { public string Path { get; set; } = ""; }
    private sealed class ErrorResponse { public string Error { get; set; } = ""; }
}

