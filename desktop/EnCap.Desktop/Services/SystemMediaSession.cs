using Avalonia.Controls;
using Avalonia.Threading;
using System.Runtime.InteropServices;
namespace EnCap;
// The UI is identical on all targets; SMTC and MPRIS are narrow native adapters.
public sealed class SystemMediaSession : IMediaSession
{
    private readonly EditorViewModel editor;
    private readonly Window window;
    private readonly Native.ActionCallback callback;
    private bool opened, disposed;
    public SystemMediaSession(Window window, EditorViewModel editor)
    {
        this.window = window;
        this.editor = editor;
        callback = OnAction;
        if (!OperatingSystem.IsWindows() && !OperatingSystem.IsLinux())
            return;
        opened = Native.Open(window.TryGetPlatformHandle()?.Handle ?? IntPtr.Zero, callback) == 0;
        if (!opened)
            editor.Status = "System media controls are unavailable; playback controls remain available in EnCap.";
    }
    private void OnAction(int action, double value) => Dispatcher.UIThread.Post(async () =>
    {
        if (disposed || editor.IsBusy)
            return;
        try
        {
            switch (action)
            {
                case 1:
                    if (!editor.Playback.IsPlaying)
                        await editor.TogglePlaybackAsync();
                    break;
                case 2:
                    editor.Pause();
                    break;
                case 3:
                    editor.Pause();
                    await editor.SeekAsync(0);
                    break;
                case 4:
                    await editor.AdjacentAsync(1);
                    break;
                case 5:
                    await editor.AdjacentAsync(-1);
                    break;
                case 6:
                    await editor.SeekAsync(value);
                    break;
                case 7:
                    window.Activate();
                    break;
                case 8:
                    editor.Playback.Play(value);
                    break;
                case 9:
                    editor.Playback.Volume = value;
                    break;
                case 10:
                    await editor.TogglePlaybackAsync();
                    break;
            }
            Update();
        }
        catch (Exception error) { editor.Fail(error); }
    });
    public void Update()
    {
        if (opened && !disposed)
            Native.Update(editor.MediaTitle, editor.PlaybackPosition, editor.PlaybackDuration, editor.Playback.Rate, editor.Playback.IsPlaying ? 1 : 0, editor.HasProject && !editor.IsBusy ? 1 : 0, editor.Playback.Volume);
    }
    public void Dispose()
    {
        disposed = true;
        if (opened)
            Native.Close();
        opened = false;
        GC.KeepAlive(callback);
    }
    private static class Native
    {
        private const string Library = "encap-media";
        [UnmanagedFunctionPointer(CallingConvention.Cdecl)] internal delegate void ActionCallback(int action, double value);
        [DllImport(Library, EntryPoint = "encap_media_open", CallingConvention = CallingConvention.Cdecl)] internal static extern int Open(IntPtr window, ActionCallback callback);
        [DllImport(Library, EntryPoint = "encap_media_update", CallingConvention = CallingConvention.Cdecl)] internal static extern void Update([MarshalAs(UnmanagedType.LPUTF8Str)] string title, double position, double duration, double rate, int playing, int enabled, double volume);
        [DllImport(Library, EntryPoint = "encap_media_close", CallingConvention = CallingConvention.Cdecl)] internal static extern void Close();
    }
}
