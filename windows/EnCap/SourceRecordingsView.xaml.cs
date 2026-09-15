using System.ComponentModel;
using Microsoft.UI.Input;
using Windows.Media;
using Windows.UI.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Windows.Foundation;
using Windows.Media.Core;
using Windows.Media.Playback;
using Windows.System;

namespace EnCap;

public sealed partial class SourceRecordingsView : UserControl
{
    private readonly SemaphoreSlim waveformGate = new(1, 1);
    private CancellationTokenSource waveformCancellation = new();
    private readonly HashSet<SourceRecordingItem> waveformRequests = [];
    private readonly Dictionary<string, double[]> waveformCache = [];
    private MediaPlayer? player;
    private MediaSource? mediaSource;
    private SourceRecordingItem? activeItem;
    private bool wantsPlayback;
    private bool mediaReady;
    private bool playbackEnded;
    private double playbackRate = 1;
    private bool slowPlayback;
    private readonly MenuFlyoutItem playItem = new() { Text = "Play" };
    private readonly MenuFlyout menu = new();
    private readonly MenuFlyoutItem deleteItem = new() { Text = "Delete Tracks…" };
    private IReadOnlyList<AudioSource> contextSources = [];
    public event Action? AddRequested;
    public event Action<IReadOnlyList<AudioSource>>? DeleteRequested;
    public event Action? PreviewStarting;
    public event Action<Exception>? PlaybackFailed;
    public double DefaultColumnWidth { get; private set; } = 220;

    public SourceRecordingsView()
    {
        InitializeComponent();
        var add = new MenuFlyoutItem { Text = "Add Audio Files…" };
        ToolTipService.SetToolTip(add, "Add WAV or AIFF recordings to this episode");
        ToolTipService.SetToolTip(deleteItem, "Remove selected imports and their chapters; original files stay on disk");
        add.Click += (_, _) => AddRequested?.Invoke();
        deleteItem.Click += (_, _) => DeleteRequested?.Invoke(contextSources);
        playItem.Click += (_, _) => {
            var item = SourceList.Items.Cast<SourceRecordingItem>().FirstOrDefault(item => contextSources.Contains(item.Source));
            if (item is not null) Play(item);
        };
        menu.Items.Add(playItem);
        menu.Items.Add(add);
        menu.Items.Add(deleteItem);
        Unloaded += (_, _) => { StopPlayback(); CancelWaveforms(); };
    }

    public void SetSources(IEnumerable<AudioSource> sources)
    {
        CancelWaveforms();
        StopPlayback();
        IsEnabled = true;
        var items = sources.Select(source => new SourceRecordingItem(source)).ToList();
        SourceList.ItemsSource = items;
        var widths = items.Select(item => {
            var label = new TextBlock { Text = item.DisplayName, FontSize = 14 };
            label.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            return label.DesiredSize.Width;
        }).ToList();
        DefaultColumnWidth = Math.Max(180, (widths.Count == 0 ? 140 : widths.Min()) + 48);
    }

    public void StopPlayback()
    {
        var previous = player;
        player = null; // Ignore callbacks queued by the old player during disposal.
        wantsPlayback = false;
        mediaReady = false;
        playbackEnded = false;
        if (activeItem is not null) { activeItem.IsPlaying = false; activeItem.IsPaused = false; }
        activeItem = null;
        if (previous is not null) previous.SystemMediaTransportControls.IsEnabled = false;
        playbackRate = 1; slowPlayback = false;
        previous?.Pause();
        previous?.Dispose();
        mediaSource?.Dispose();
        mediaSource = null;
    }

    private void Playback_Click(object sender, RoutedEventArgs args)
    {
        if ((sender as FrameworkElement)?.DataContext is SourceRecordingItem item) Toggle(item);
    }

    private void Toggle(SourceRecordingItem item)
    {
        if (activeItem == item && wantsPlayback) Pause();
        else Play(item);
    }

    private void Pause()
    {
        wantsPlayback = false;
        player?.Pause();
        if (activeItem is not null) { activeItem.IsPlaying = false; activeItem.IsPaused = true; }
        UpdateMediaControls();
    }

    private void Play(SourceRecordingItem item, double rate = 1)
    {
        try
        {
            if (activeItem == item && player is not null)
            {
                if (playbackEnded && rate > 0) player.PlaybackSession.Position = TimeSpan.Zero;
                playbackEnded = false;
                playbackRate = rate;
                wantsPlayback = true;
                PreviewStarting?.Invoke();
                ApplyRate();
                return;
            }
            StopPlayback();
            PreviewStarting?.Invoke();
            var next = new MediaPlayer { AutoPlay = false, IsLoopingEnabled = false };
            player = next;
            activeItem = item;
            playbackRate = rate;
            next.CommandManager.IsEnabled = false;
            var controls = next.SystemMediaTransportControls;
            controls.IsEnabled = true;
            controls.IsPlayEnabled = controls.IsPauseEnabled = controls.IsStopEnabled = true;
            controls.IsNextEnabled = controls.IsPreviousEnabled = true;
            controls.ButtonPressed += (_, args) => DispatcherQueue.TryEnqueue(() => {
                if (player != next) return;
                switch (args.Button) {
                    case SystemMediaTransportControlsButton.Play: Play(item); break;
                    case SystemMediaTransportControlsButton.Pause: Pause(); break;
                    case SystemMediaTransportControlsButton.Stop: Pause(); next.PlaybackSession.Position = TimeSpan.Zero; break;
                    case SystemMediaTransportControlsButton.Next: Adjacent(1); break;
                    case SystemMediaTransportControlsButton.Previous: Adjacent(-1); break;
                }
                UpdateMediaControls();
            });
            controls.PlaybackPositionChangeRequested += (_, args) => DispatcherQueue.TryEnqueue(() => {
                if (player != next) return;
                next.PlaybackSession.Position = TimeSpan.FromSeconds(Math.Clamp(args.RequestedPlaybackPosition.TotalSeconds, 0, item.Source.DurationSeconds));
                UpdateMediaControls();
            });
            controls.DisplayUpdater.Type = MediaPlaybackType.Music;
            controls.DisplayUpdater.MusicProperties.Title = item.DisplayName;
            controls.DisplayUpdater.Update();
            next.MediaOpened += (_, _) => DispatcherQueue.TryEnqueue(() => { if (player == next) { mediaReady = true; ApplyRate(); } });
            next.PlaybackSession.PlaybackStateChanged += (_, _) => DispatcherQueue.TryEnqueue(() => {
                if (player != next) return;
                var state = next.PlaybackSession.PlaybackState;
                item.IsPlaying = wantsPlayback && state is MediaPlaybackState.Playing or MediaPlaybackState.Opening or MediaPlaybackState.Buffering;
                UpdateMediaControls();
            });
            next.MediaEnded += (_, _) => DispatcherQueue.TryEnqueue(() => {
                if (player != next) return;
                Pause(); playbackEnded = true; UpdateMediaControls();
            });
            next.MediaFailed += (_, error) => DispatcherQueue.TryEnqueue(() => {
                if (player != next) return;
                StopPlayback();
                PlaybackFailed?.Invoke(new InvalidOperationException($"Could not play {item.DisplayName}: {error.ErrorMessage}"));
            });
            mediaSource = MediaSource.CreateFromUri(new Uri(item.Source.SourcePath));
            next.Source = mediaSource;
            wantsPlayback = true;
            item.IsPlaying = true;
            UpdateMediaControls();
        }
        catch (Exception error) { StopPlayback(); PlaybackFailed?.Invoke(error); }
    }

    private void ApplyRate()
    {
        try { ApplyRateCore(); }
        catch (Exception error) { StopPlayback(); PlaybackFailed?.Invoke(error); }
    }

    private void ApplyRateCore()
    {
        if (player is null || activeItem is null || !wantsPlayback || !mediaReady) return;
        if (!player.PlaybackSession.IsSupportedPlaybackRateRange(playbackRate, playbackRate))
        {
            Pause();
            PlaybackFailed?.Invoke(new InvalidOperationException($"This recording’s Windows decoder does not support {playbackRate}× playback."));
            return;
        }
        player.PlaybackSession.PlaybackRate = playbackRate;
        player.Play();
        activeItem.IsPlaying = true;
        activeItem.IsPaused = false;
        ToolTipService.SetToolTip(SourceList, $"Playing at {playbackRate}×. Space: play/pause; J/K/L: reverse/pause/forward; hold K for half speed.");
        UpdateMediaControls();
    }

    private void UpdateMediaControls()
    {
        if (player is null || activeItem is null) return;
        var controls = player.SystemMediaTransportControls;
        controls.PlaybackStatus = wantsPlayback ? MediaPlaybackStatus.Playing : MediaPlaybackStatus.Paused;
        var items = SourceList.Items.Cast<SourceRecordingItem>().ToList();
        int index = items.IndexOf(activeItem);
        controls.IsPreviousEnabled = index > 0;
        controls.IsNextEnabled = index >= 0 && index + 1 < items.Count;
        controls.UpdateTimelineProperties(new SystemMediaTransportControlsTimelineProperties {
            StartTime = TimeSpan.Zero, MinSeekTime = TimeSpan.Zero,
            EndTime = TimeSpan.FromSeconds(activeItem.Source.DurationSeconds),
            MaxSeekTime = TimeSpan.FromSeconds(activeItem.Source.DurationSeconds),
            Position = player.PlaybackSession.Position
        });
    }

    private void Adjacent(int direction)
    {
        var items = SourceList.Items.Cast<SourceRecordingItem>().ToList();
        int next = (activeItem is null ? -1 : items.IndexOf(activeItem)) + direction;
        if (next < 0 || next >= items.Count) return;
        SourceList.SelectedItem = items[next];
        Play(items[next]);
    }

    private SourceRecordingItem? SelectedItem() => SourceList.Items.Cast<SourceRecordingItem>()
        .FirstOrDefault(item => SourceList.SelectedItems.Contains(item));

    private void List_DoubleTapped(object sender, DoubleTappedRoutedEventArgs args)
    {
        DependencyObject? element = args.OriginalSource as DependencyObject;
        while (element is not null && element != SourceList && element is not ListViewItem) {
            if (element is Button) return;
            element = VisualTreeHelper.GetParent(element);
        }
        if (element is ListViewItem { Content: SourceRecordingItem item }) { Play(item); args.Handled = true; }
    }

    private void List_RightTapped(object sender, RightTappedRoutedEventArgs args)
    {
        DependencyObject? element = args.OriginalSource as DependencyObject;
        while (element is not null && element != SourceList && element is not ListViewItem)
            element = VisualTreeHelper.GetParent(element);
        if (element is ListViewItem row && row.Content is SourceRecordingItem item)
        {
            if (!SourceList.SelectedItems.Contains(item))
            {
                SourceList.SelectedItems.Clear();
                SourceList.SelectedItems.Add(item);
            }
            contextSources = SelectedSources();
        }
        else contextSources = [];
        ShowContextMenu(args.GetPosition(SourceList));
        args.Handled = true;
    }

    private IReadOnlyList<AudioSource> SelectedSources() => SourceList.SelectedItems.Cast<SourceRecordingItem>().Select(item => item.Source).ToArray();

    private void ShowContextMenu(Point position)
    {
        playItem.Visibility = contextSources.Count == 0 ? Visibility.Collapsed : Visibility.Visible;
        deleteItem.Visibility = contextSources.Count == 0 ? Visibility.Collapsed : Visibility.Visible;
        deleteItem.Text = contextSources.Count == 1 ? "Delete Track…" : "Delete Tracks…";
        menu.ShowAt(SourceList, new Microsoft.UI.Xaml.Controls.Primitives.FlyoutShowOptions { Position = position });
    }

    private void List_KeyDown(object sender, KeyRoutedEventArgs args)
    {
        bool Down(VirtualKey key) => (InputKeyboardSource.GetKeyStateForCurrentThread(key) & CoreVirtualKeyStates.Down) != 0;
        if (Down(VirtualKey.Control) || Down(VirtualKey.Menu) || Down(VirtualKey.LeftWindows) || Down(VirtualKey.RightWindows)) return;
        if (args.Key is VirtualKey.Space or VirtualKey.J or VirtualKey.K or VirtualKey.L)
        {
            if (Down(VirtualKey.Shift)) return;
            args.Handled = true;
            if (args.KeyStatus.WasKeyDown) return;
            var item = SelectedItem();
            if (item is null) return;
            if (args.Key == VirtualKey.Space) { slowPlayback = false; Toggle(item); }
            else if (args.Key == VirtualKey.K) Pause();
            else {
                var slow = Down(VirtualKey.K);
                double current = wantsPlayback && activeItem == item ? playbackRate : 0;
                Play(item, SourceShuttle.Rate(current, args.Key == VirtualKey.J ? -1 : 1, slow));
                slowPlayback = slow;
            }
            return;
        }
        if (args.Key == VirtualKey.Delete || args.Key == VirtualKey.Back)
        {
            var sources = SelectedSources();
            if (sources.Count > 0) DeleteRequested?.Invoke(sources);
            args.Handled = true;
        }
        else if (args.Key == VirtualKey.Application)
        {
            contextSources = SelectedSources();
            ShowContextMenu(new Point(12, 12));
            args.Handled = true;
        }
    }

    public void ReleaseShuttleChord()
    {
        if (slowPlayback) { slowPlayback = false; Pause(); }
    }

    private void List_LostFocus(object sender, RoutedEventArgs args)
    {
        DispatcherQueue.TryEnqueue(() => {
            RefreshVisibleRows();
            var focus = FocusManager.GetFocusedElement(XamlRoot) as DependencyObject;
            while (focus is not null && focus != SourceList) focus = VisualTreeHelper.GetParent(focus);
            if (focus is null) ReleaseShuttleChord();
        });
    }

    private void List_KeyUp(object sender, KeyRoutedEventArgs args)
    {
        if (args.Key is VirtualKey.Space or VirtualKey.J or VirtualKey.K or VirtualKey.L) {
            args.Handled = true;
            if (slowPlayback) { slowPlayback = false; Pause(); }
        }
    }

    private static Button PlaybackButton(Grid row) => (Button)row.FindName("PlaybackButton");

    private void RefreshRow(Grid row)
    {
        var button = PlaybackButton(row);
        var container = SourceList.ContainerFromItem(row.DataContext) as ListViewItem;
        bool selected = SourceList.SelectedItems.Contains(row.DataContext);
        bool keyboardFocus = container?.FocusState == FocusState.Keyboard || button.FocusState == FocusState.Keyboard;
        button.Opacity = row.Tag is true || selected || keyboardFocus ? 1 : 0.4;
        if (row.FindName("Waveform") is SourceWaveform waveform) waveform.Opacity = selected || keyboardFocus ? 1 : 0.45;
    }

    private void RefreshVisibleRows()
    {
        foreach (var item in SourceList.Items)
            if (SourceList.ContainerFromItem(item) is ListViewItem { ContentTemplateRoot: Grid row }) RefreshRow(row);
    }

    private void List_SelectionChanged(object sender, SelectionChangedEventArgs args) => RefreshVisibleRows();
    private void List_GotFocus(object sender, RoutedEventArgs args) => RefreshVisibleRows();
    private void Row_DataContextChanged(FrameworkElement sender, DataContextChangedEventArgs args)
    {
        if (sender.IsLoaded) Row_Loaded(sender, new RoutedEventArgs());
    }

    private async void Row_Loaded(object sender, RoutedEventArgs args)
    {
        var row = (Grid)sender;
        RefreshRow(row);
        if (row.DataContext is not SourceRecordingItem item || !waveformRequests.Add(item)) return;
        var token = waveformCancellation.Token;
        try {
            await Task.Delay(150, token);
            await waveformGate.WaitAsync(token);
            try {
                if (!row.IsLoaded || row.DataContext != item) { waveformRequests.Remove(item); return; }
                if (!waveformCache.TryGetValue(item.Source.SourcePath, out var peaks)) {
                    peaks = await new EngineClient().WaveformAsync(item.Source.SourcePath, token);
                    if (waveformCache.Count >= 512) waveformCache.Remove(waveformCache.Keys.First());
                    waveformCache[item.Source.SourcePath] = peaks;
                }
                if (!token.IsCancellationRequested) item.WaveformPeaks = peaks;
            } finally { waveformGate.Release(); }
        } catch (OperationCanceledException) { }
          catch { if (!token.IsCancellationRequested) item.WaveformPeaks = []; }
    }

    private void CancelWaveforms()
    {
        waveformCancellation.Cancel(); waveformCancellation.Dispose();
        waveformCancellation = new CancellationTokenSource();
        waveformRequests.Clear();
    }
    private void Row_PointerEntered(object sender, PointerRoutedEventArgs args) { var row = (Grid)sender; row.Tag = true; RefreshRow(row); }
    private void Row_PointerExited(object sender, PointerRoutedEventArgs args) { var row = (Grid)sender; row.Tag = false; RefreshRow(row); }
    private void Row_GotFocus(object sender, RoutedEventArgs args) => RefreshRow((Grid)sender);
    private void Row_LostFocus(object sender, RoutedEventArgs args) => RefreshRow((Grid)sender);

}

public sealed class SourceRecordingItem(AudioSource source) : INotifyPropertyChanged
{
    public AudioSource Source { get; } = source;
    public string DisplayName => Source.DisplayName;
    public string FileTypeLabel => Path.GetExtension(Source.SourcePath).ToLowerInvariant() switch {
        ".wav" or ".wave" => "WAV",
        ".aif" or ".aiff" or ".aifc" => "AIFF",
        var extension => extension.TrimStart('.').ToUpperInvariant()
    };
    public string DurationLabel => $"{(int)Source.DurationSeconds / 60}:{(int)Source.DurationSeconds % 60:00}";
    private double[] waveformPeaks = [];
    public double[] WaveformPeaks {
        get => waveformPeaks;
        set { waveformPeaks = value; PropertyChanged?.Invoke(this, new(nameof(WaveformPeaks))); }
    }
    private bool isPlaying;
    public bool IsPlaying {
        get => isPlaying;
        set {
            if (isPlaying == value) return;
            isPlaying = value;
            PropertyChanged?.Invoke(this, new(nameof(PlaybackGlyph)));
            PropertyChanged?.Invoke(this, new(nameof(PlaybackLabel)));
        }
    }
    private bool isPaused;
    public bool IsPaused {
        get => isPaused;
        set {
            if (isPaused == value) return;
            isPaused = value;
            PropertyChanged?.Invoke(this, new(nameof(PlaybackLabel)));
        }
    }
    public string PlaybackGlyph => IsPlaying ? "\uE769" : "\uE768";
    public string PlaybackLabel => $"{(IsPlaying ? "Pause" : IsPaused ? "Resume" : "Play")} {DisplayName}";
    public event PropertyChangedEventHandler? PropertyChanged;
}
