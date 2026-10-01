using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Markup.Xaml;
using Avalonia.Styling;
using Avalonia.Threading;
using Avalonia.VisualTree;
using Avalonia.Platform.Storage;
namespace EnCap;

public sealed partial class MainWindow : Window
{
    public EditorViewModel Editor
    {
        get;
    }
    private readonly DispatcherTimer clock = new() { Interval = TimeSpan.FromMilliseconds(100) };
    private readonly DispatcherTimer updates = new() { Interval = TimeSpan.FromHours(1) };
    private bool closing, closePending, slow;
    private readonly IApplicationUpdates? updater;
    private IMediaSession? media;
    private readonly HashSet<Key> heldKeys = [];
    public MainWindow() : this([]) { }
    public MainWindow(string[] args) : this(null, null, null, args) { }
    public MainWindow(IEngineClient? engine, IUserDialogs? dialogs, IPlayback? playback, string[]? args = null)
    {
        AvaloniaXamlLoader.Load(this);
        Editor = new(engine ?? new EngineClient(), dialogs ?? new Dialogs(this), playback ?? new NativePlayback());
        DataContext = Editor;
        if (engine is null && AppIdentity.ProductionUpdatesAllowed)
            updater = new UpdateService(this, Editor, new Dialogs(this));
        this.FindControl<MenuItem>("CheckUpdatesMenu")!.IsEnabled = updater is not null;
        var automatic = this.FindControl<MenuItem>("AutomaticUpdatesMenu")!;
        automatic.IsEnabled = updater is not null;
        automatic.IsChecked = updater?.Automatic ?? false;
        clock.Tick += (_, _) => { Editor.Tick(); media?.Update(); };
        updates.Tick += async (_, _) => { if (updater?.Automatic == true) await updater.CheckAsync(false); };
        Opened += async (_, _) =>
        {
            if (playback is null)
            {
                try
                {
                    media = new SystemMediaSession(this, Editor);
                }
                catch (Exception error) { Editor.Fail(error); }
            }
            clock.Start();
            await Editor.InitializeAsync();
            if (OperatingSystem.IsWindows() && Environment.GetEnvironmentVariable("ENCAP_UPDATE_STARTUP_ACK") is string acknowledgement)
            {
                try
                {
                    File.WriteAllText(acknowledgement, "ready");
                }
                catch (IOException error) { Editor.Fail(error); }
            }
            if (args?.FirstOrDefault() is string path && File.Exists(path))
                await Guard(() => Editor.OpenPathAsync(path));
            updates.Start();
            if (updater?.Automatic == true)
                await updater.CheckAsync(false);
        };
        Closing += async (_, e) => { if (closing) return; e.Cancel = true; if (closePending) return; closePending = true; try { if (await Editor.CanCloseAsync()) { closing = true; Close(); } } catch (Exception error) { Editor.Fail(error); } finally { closePending = false; } };
        Closed += (_, _) => { clock.Stop(); updates.Stop(); media?.Dispose(); Editor.Dispose(); };
        Deactivated += (_, _) => { if (slow) Editor.Pause(); slow = false; heldKeys.Clear(); };
        AddHandler(DragDrop.DropEvent, FilesDropped);
        this.FindControl<ListBox>("VideoList")!.AddHandler(DragDrop.DropEvent, VideoDropped);
        AddHandler(KeyDownEvent, MediaKeyDown, RoutingStrategies.Tunnel);
    }
    public async Task<bool> CloseForUpdateAsync()
    {
        IsEnabled = false;
        try
        {
            if (!await Editor.CanCloseAsync())
                return false;
            closing = true;
            Close();
            return true;
        }
        finally { if (!closing) IsEnabled = true; }
    }
    private async Task Guard(Func<Task> action)
    {
        try
        {
            await action();
        }
        catch (Exception error) { Editor.Fail(error); }
    }
    private async void RemoveSources(object? sender, RoutedEventArgs e) => await Guard(() => Editor.RemoveSourcesAsync(this.FindControl<ListBox>("SourceList")!.SelectedItems?.OfType<SourceItem>().Select(s => s.Source).ToArray() ?? []));
    private async void SourceDoubleTapped(object? sender, TappedEventArgs e) => await Editor.PlayCommand.ExecuteAsync();
    private async void VideoDoubleTapped(object? sender, TappedEventArgs e) => await Guard(Editor.PreviewChapterAsync);
    private async void SeekKeyUp(object? sender, KeyEventArgs e)
    {
        if (sender is Slider slider && e.Key is Key.Left or Key.Right or Key.Up or Key.Down or Key.Home or Key.End or Key.PageUp or Key.PageDown)
            await Guard(() => Editor.SeekAsync(slider.Value));
    }
    private async void SeekReleased(object? sender, PointerReleasedEventArgs e)
    {
        if (sender is Slider slider)
            await Guard(() => Editor.SeekAsync(slider.Value));
    }
    private async void SourceKeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Source is TextBox)
            return;
        if (e.Key is Key.J or Key.K or Key.L or Key.Space && !heldKeys.Add(e.Key))
        {
            e.Handled = true;
            return;
        }
        switch (e.Key)
        {
            case Key.Space:
                await Editor.PlayCommand.ExecuteAsync();
                break;
            case Key.K:
                slow = true;
                Editor.Pause();
                break;
            case Key.J:
                await Guard(() => Editor.ShuttleAsync(-1, slow));
                break;
            case Key.L:
                await Guard(() => Editor.ShuttleAsync(1, slow));
                break;
            case Key.Back:
            case Key.Delete:
                RemoveSources(sender, e);
                break;
            default:
                return;
        }
        e.Handled = true;
    }
    private void SourceKeyUp(object? sender, KeyEventArgs e)
    {
        heldKeys.Remove(e.Key);
        if (e.Key == Key.K)
        {
            slow = false;
            Editor.Pause();
        }
        else if (slow && (e.Key == Key.J || e.Key == Key.L))
            Editor.Pause();
    }
    private async void MediaKeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Key == Key.MediaPlayPause)
            await Editor.PlayCommand.ExecuteAsync();
        else if (e.Key == Key.MediaNextTrack)
            await Editor.NextCommand.ExecuteAsync();
        else if (e.Key == Key.MediaPreviousTrack)
            await Editor.PreviousCommand.ExecuteAsync();
        else if (e.Key == Key.MediaStop)
        {
            Editor.Pause();
            await Guard(() => Editor.SeekAsync(0));
        }
        else
            return;
        e.Handled = true;
    }
    private async void FilesDropped(object? sender, DragEventArgs e)
    {
        if (e.Handled || Editor.IsBusy)
            return;
        var paths = e.DataTransfer.TryGetFiles()?.Select(f => f.TryGetLocalPath()).OfType<string>().ToArray() ?? [];
        if (paths.Length == 0)
            return;
        e.Handled = true;
        await Guard(async () => { if (paths.Length == 1 && Path.GetExtension(paths[0]).Equals(".encap", StringComparison.OrdinalIgnoreCase)) await Editor.OpenPathAsync(paths[0]); else await Editor.AddFilesAsync(paths); });
    }
    private Point dragStart; private PointerPressedEventArgs? dragPress; private VideoItem? dragged;
    private void VideoDragStart(object? sender, PointerPressedEventArgs e)
    {
        dragPress = e;
        dragStart = e.GetPosition(this);
        dragged = (e.Source as Control)?.DataContext as VideoItem;
    }
    private async void VideoDragMove(object? sender, PointerEventArgs e)
    {
        if (dragged is null || !e.GetCurrentPoint(this).Properties.IsLeftButtonPressed || Math.Abs(e.GetPosition(this).X - dragStart.X) + Math.Abs(e.GetPosition(this).Y - dragStart.Y) < 8)
            return;
        var item = dragged;
        dragged = null;
        var transfer = new DataTransfer();
        var data = new DataTransferItem();
        data.SetText("encap-video:" + item.Chapter.Id);
        transfer.Add(data);
        await DragDrop.DoDragDropAsync(dragPress!, transfer, DragDropEffects.Move);
    }
    private void VideoDropped(object? sender, DragEventArgs e)
    {
        var text = e.DataTransfer.TryGetText();
        if (text?.StartsWith("encap-video:") != true)
            return;
        var target = (e.Source as Control)?.GetSelfAndVisualAncestors().OfType<Control>().Select(c => c.DataContext).OfType<VideoItem>().FirstOrDefault();
        var item = Editor.VideoChapters.FirstOrDefault(c => "encap-video:" + c.Chapter.Id == text);
        if (item is not null && target is not null)
            Editor.ReorderVideo(item, Editor.VideoChapters.IndexOf(target));
        e.Handled = true;
    }
    private async void CheckUpdates(object? sender, RoutedEventArgs e)
    {
        if (updater is not null)
            await updater.CheckAsync(true);
    }
    private void ToggleUpdates(object? sender, RoutedEventArgs e)
    {
        if (updater is not null && sender is MenuItem item)
        {
            try
            {
                updater.Automatic = item.IsChecked;
            }
            catch (Exception error) { Editor.Fail(error); }
        }
    }
    private void SetTheme(ThemeVariant variant)
    {
        if (Application.Current is not null)
            Application.Current.RequestedThemeVariant = variant;
    }
    private void ThemeSystem(object? sender, RoutedEventArgs e) => SetTheme(ThemeVariant.Default); private void ThemeLight(object? sender, RoutedEventArgs e) => SetTheme(ThemeVariant.Light); private void ThemeDark(object? sender, RoutedEventArgs e) => SetTheme(ThemeVariant.Dark);
}
