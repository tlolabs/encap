using System.Diagnostics;
using System.Text.Json;
using Avalonia.Controls;
namespace EnCap;

public sealed class UpdateService(MainWindow window, EditorViewModel editor, IUserDialogs dialogs) : IApplicationUpdates
{
    private bool running;
    private static string Preference => OperatingSystem.IsLinux() ? Path.Combine(Environment.GetEnvironmentVariable("XDG_CONFIG_HOME") ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".config"), "com.tlolabs.encap", "automatic-updates-disabled") : Path.Combine(AppIdentity.DataDirectory, "automatic-updates-disabled");
    public bool Automatic
    {
        get => !File.Exists(Preference); set
        {
            Directory.CreateDirectory(Path.GetDirectoryName(Preference)!);
            if (value)
                File.Delete(Preference);
            else
                File.WriteAllText(Preference, "disabled");
        }
    }
    public async Task CheckAsync(bool manual)
    {
        if (!AppIdentity.ProductionUpdatesAllowed || running || editor.IsBusy)
            return;
        running = true;
        try
        {
            var result = await RunAsync(manual ? "check" : "check-auto");
            if (!result.GetProperty("available").GetBoolean())
            {
                if (manual)
                    editor.Status = "No newer compatible stable update is available.";
                return;
            }
            var version = result.GetProperty("version").GetString();
            if (result.TryGetProperty("manual_migration", out var migration) && migration.GetBoolean())
            {
                editor.Status = "This update requires manual migration: " + result.GetProperty("release_notes_url").GetString();
                return;
            }
            if (!await dialogs.ConfirmAsync("EnCap " + version + " is available", "Download and install this authenticated update? Save your project first."))
                return;
            manual = true;
            if (editor.IsDirty || editor.IsBusy)
            {
                editor.Status = "Save your work and finish the current operation before updating.";
                return;
            }
            if (OperatingSystem.IsLinux() && Environment.GetEnvironmentVariable("APPIMAGE") is not null)
            {
                await RunAsync("install-appimage");
                editor.Status = "Update installed. Save and restart EnCap when ready; the previous AppImage is retained.";
                return;
            }
            var download = await RunAsync("download");
            if (editor.IsDirty || editor.IsBusy)
            {
                editor.Status = "Update downloaded. Save your work before installing.";
                return;
            }
            if (OperatingSystem.IsLinux())
            {
                editor.Status = "Verified update downloaded to " + download.GetProperty("path").GetString() + ". Replace your AppImage after quitting.";
                return;
            }
            var directory = Path.Combine(Path.GetTempPath(), "encap-portable-helper-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(directory);
            var helper = Path.Combine(directory, "encap-portable-update.exe");
            File.Copy(Path.Combine(AppContext.BaseDirectory, "encap-portable-update.exe"), helper);
            var ready = Path.Combine(directory, "ready");
            var start = new ProcessStartInfo(helper) { UseShellExecute = false, RedirectStandardError = true };
            foreach (var arg in new[] { download.GetProperty("path").GetString()!, download.GetProperty("sha256").GetString()!, AppContext.BaseDirectory, Environment.ProcessId.ToString(), download.GetProperty("target").GetString()!, download.GetProperty("version").GetString()!, ready })
                start.ArgumentList.Add(arg);
            using var process = Process.Start(start) ?? throw new IOException("Cannot start the update installer.");
            var errors = process.StandardError.ReadToEndAsync();
            var deadline = DateTime.UtcNow.AddMinutes(2);
            while (!File.Exists(ready))
            {
                if (process.HasExited)
                    throw new IOException(await errors);
                if (DateTime.UtcNow >= deadline)
                {
                    process.Kill(true);
                    throw new IOException("Installer verification timed out; EnCap remains open.");
                }
                await Task.Delay(100);
            }
            if (editor.IsDirty || editor.IsBusy)
            {
                process.Kill(true);
                editor.Status = "Installation cancelled because the project changed. Save and retry.";
                return;
            }
            if (!await window.CloseForUpdateAsync())
            {
                process.Kill(true);
                editor.Status = "Installation cancelled; EnCap remains open.";
            }

        }
        catch (Exception e) { if (manual) editor.Fail(e); }
        finally { running = false; }
    }
    public static async Task<JsonElement> RunAsync(string command)
    {
        if (!AppIdentity.ProductionUpdatesAllowed)
            throw new InvalidOperationException("The internal reference build cannot access production updates.");
        var start = new ProcessStartInfo(Path.Combine(AppContext.BaseDirectory, OperatingSystem.IsWindows() ? "encap-update.exe" : "encap-update")) { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true };
        start.ArgumentList.Add(command);
        using var p = Process.Start(start) ?? throw new IOException("Cannot start update helper.");
        var stdout = p.StandardOutput.ReadToEndAsync();
        var stderr = p.StandardError.ReadToEndAsync();
        await p.WaitForExitAsync();
        if (p.ExitCode != 0)
            throw new IOException(await stderr);
        using var json = JsonDocument.Parse(await stdout);
        return json.RootElement.Clone();
    }
}
