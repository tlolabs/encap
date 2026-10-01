using System.Diagnostics;
using System.Runtime.InteropServices;
namespace EnCap;

public sealed class NativePlayback : IPlayback
{
    private string? temporary;
    private bool loaded;
    private double volume = 1;
    public double Volume
    {
        get => volume; set
        {
            if (!double.IsFinite(value) || value < 0 || value > 1)
                throw new ArgumentOutOfRangeException(nameof(value));
            volume = value;
            Native.Volume(value);
        }
    }
    public double Position => loaded ? Native.Position() : 0;
    public double Rate { get; private set; } = 1;
    public bool IsPlaying => loaded && Native.Playing() != 0;
    public async Task OpenAsync(string path, CancellationToken cancellationToken = default)
    {
        Stop();
        if (Native.Open(path) == 0)
        {
            loaded = true;
            Native.Volume(volume);
            return;
        }
        Native.Close();
        // AIFF and other PCM variants are decoded by the existing authenticated FFmpeg runtime.
        var engine = Path.Combine(AppContext.BaseDirectory, OperatingSystem.IsWindows() ? "encap-engine.exe" : "encap-engine");
        var check = new ProcessStartInfo(engine) { UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true, CreateNoWindow = true };
        check.ArgumentList.Add("validate-tools");
        await RunAsync(check, cancellationToken);
        temporary = Path.Combine(Path.GetTempPath(), "encap-preview-" + Guid.NewGuid().ToString("N") + ".wav");
        var ff = new ProcessStartInfo(Path.Combine(AppContext.BaseDirectory, OperatingSystem.IsWindows() ? "ffmpeg.exe" : "ffmpeg")) { UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true, CreateNoWindow = true };
        foreach (var arg in new[] { "-nostdin", "-v", "error", "-i", path, "-vn", "-ac", "2", "-ar", "48000", "-c:a", "pcm_f32le", "-y", temporary })
            ff.ArgumentList.Add(arg);
        try
        {
            await RunAsync(ff, cancellationToken);
            if (Native.Open(temporary) != 0)
                throw new IOException("Could not open the audio preview device or recording.");
            loaded = true;
            Native.Volume(volume);
        }
        catch { Stop(); throw; }
    }
    private static async Task RunAsync(ProcessStartInfo start, CancellationToken token)
    {
        using var process = Process.Start(start) ?? throw new IOException("Could not start media decoder.");
        var output = process.StandardOutput.ReadToEndAsync();
        var errors = process.StandardError.ReadToEndAsync();
        try
        {
            await process.WaitForExitAsync(token);
        }
        catch (OperationCanceledException) { if (!process.HasExited) process.Kill(true); await process.WaitForExitAsync(); throw; }
        await output;
        var error = await errors;
        if (process.ExitCode != 0)
            throw new IOException(error.Length == 0 ? "Media verification/decoding failed." : error);
    }
    public void Play(double rate = 1)
    {
        if (!loaded)
            return;
        if (!double.IsFinite(rate) || Math.Abs(rate) > 32)
            throw new ArgumentOutOfRangeException(nameof(rate));
        Rate = rate;
        Native.Play(rate);
    }
    public void Pause()
    {
        if (loaded)
            Native.Pause();
    }
    public void Seek(double seconds)
    {
        if (loaded && double.IsFinite(seconds))
            Native.Seek(seconds);
    }
    public void Stop()
    {
        Native.Close();
        loaded = false;
        Rate = 1;
        if (temporary is not null)
        {
            try
            {
                File.Delete(temporary);
            }
            catch (IOException) { }
            temporary = null;
        }
    }
    public void Dispose() => Stop();
    private static class Native
    {
        private const string Library = "encap-playback";
        [DllImport(Library, EntryPoint = "encap_audio_volume", CallingConvention = CallingConvention.Cdecl)] internal static extern void Volume(double value);
        [DllImport(Library, EntryPoint = "encap_audio_open", CallingConvention = CallingConvention.Cdecl)] internal static extern int Open([MarshalAs(UnmanagedType.LPUTF8Str)] string path);
        [DllImport(Library, EntryPoint = "encap_audio_play", CallingConvention = CallingConvention.Cdecl)] internal static extern void Play(double rate);
        [DllImport(Library, EntryPoint = "encap_audio_pause", CallingConvention = CallingConvention.Cdecl)] internal static extern void Pause();
        [DllImport(Library, EntryPoint = "encap_audio_seek", CallingConvention = CallingConvention.Cdecl)] internal static extern void Seek(double seconds);
        [DllImport(Library, EntryPoint = "encap_audio_position", CallingConvention = CallingConvention.Cdecl)] internal static extern double Position();
        [DllImport(Library, EntryPoint = "encap_audio_playing", CallingConvention = CallingConvention.Cdecl)] internal static extern int Playing();
        [DllImport(Library, EntryPoint = "encap_audio_close", CallingConvention = CallingConvention.Cdecl)] internal static extern void Close();
    }
}
