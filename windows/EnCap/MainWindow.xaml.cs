using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.Media.Core;
using Windows.Media.Playback;
using Windows.Storage.Pickers;
using WinRT.Interop;

namespace EnCap;

public sealed partial class MainWindow : Window
{
    private readonly EngineClient engine = new();
    private ProjectDocument? project;
    private CancellationTokenSource? recoveryDelay;
    private bool isDirty;
    private bool isPresentingProject;
    private bool isChangingMode;
    private string currentMode = "audio";
    private List<VideoPreset> videoPresets = [];
    private List<VideoChapterItem> videoChapters = [];
    private readonly DispatcherTimer videoPreviewTimer = new() { Interval = TimeSpan.FromMilliseconds(200) };
    private int videoPreviewIndex;
    private double pendingVideoPreviewSeconds;
    private bool resumeVideoPreview;
    private bool updatingVideoPreviewSeek;

    public MainWindow()
    {
        InitializeComponent();
        Title = "EnCap";
        AppWindow.Resize(new Windows.Graphics.SizeInt32(1180, 820));
        VideoPreviewPlayer.SetMediaPlayer(new MediaPlayer());
        VideoPreviewPlayer.MediaPlayer.MediaOpened += VideoPreviewMedia_Opened;
        VideoPreviewPlayer.MediaPlayer.MediaEnded += VideoPreviewMedia_Ended;
        videoPreviewTimer.Tick += VideoPreviewTimer_Tick;
        videoPreviewTimer.Start();
        _ = InitializeAsync();
    }

    private async Task InitializeAsync()
    {
        await LoadProvidersAsync();
        try
        {
            videoPresets = await engine.VideoPresetsAsync();
            VideoPresetPicker.ItemsSource = videoPresets;
            VideoPresetPicker.SelectedIndex = 0;
        }
        catch (Exception error) { ShowError(error); }
        try
        {
            var recovered = await engine.LoadRecoveryAsync();
            if (recovered is null) return;
            project = recovered;
            isDirty = true;
            PresentProject();
            Status.Message = "Recovered unsaved work from the previous session.";
        }
        catch (Exception error) { ShowError(error); }
    }

    private async Task LoadProvidersAsync()
    {
        try { Provider.ItemsSource = await engine.ProvidersAsync(); Provider.SelectedIndex = 0; }
        catch (Exception error) { ShowError(error); }
    }

    private async void Import_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker();
        InitializeWithWindow.Initialize(picker, WindowNative.GetWindowHandle(this));
        picker.FileTypeFilter.Add("*");
        var folder = await picker.PickSingleFolderAsync();
        if (folder is null) return;
        await WorkAsync("Reading audio…", async () => { project = await engine.InspectAsync(folder.Path); PresentProject(); MarkDirty(); });
    }

    private async void Open_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker();
        InitializeWithWindow.Initialize(picker, WindowNative.GetWindowHandle(this));
        picker.FileTypeFilter.Add(".encap");
        var file = await picker.PickSingleFileAsync();
        if (file is null) return;
        await WorkAsync("Opening project…", async () =>
        {
            project = await engine.OpenAsync(file.Path);
            isDirty = false;
            await engine.ClearRecoveryAsync();
            PresentProject();
        });
    }

    private async void Save_Click(object sender, RoutedEventArgs e)
    {
        if (project is null) return;
        var path = await PickSaveAsync("EnCap project", ".encap");
        if (path is null) return;
        ReadProjectEdits();
        await WorkAsync("Saving project…", async () =>
        {
            Status.Message = $"Saved {Path.GetFileName(await engine.SaveAsync(project, path))}.";
            project.ProjectPath = path;
            isDirty = false;
            await engine.ClearRecoveryAsync();
        });
    }

    private async void Export_Click(object sender, RoutedEventArgs e)
    {
        if (project is null) return;
        ReadProjectEdits();
        var extension = project.ExportSettings.OutputFormat == "aac" ? ".m4a" : ".mp3";
        var path = await PickSaveAsync("Audio", extension);
        if (path is null) return;
        await WorkAsync("Exporting audio…", async () => Status.Message = $"Exported {Path.GetFileName(await engine.ExportAsync(project, path))}." );
    }

    private async void Transcribe_Click(object sender, RoutedEventArgs e)
    {
        if (project is null || Provider.SelectedItem is not TranscriptionProvider provider) return;
        await WorkAsync("Transcribing locally…", async () => { project.TranscriptSegments = await engine.TranscribeAsync(project, provider.Id); TranscriptList.ItemsSource = project.TranscriptSegments; MarkDirty(); });
    }

    private async void ExportVideo_Click(object sender, RoutedEventArgs e)
    {
        if (project is null) return;
        ApplyVideoEdits();
        if (project.Video.ExportSettings.SelectedChapterIds.Count == 0)
        {
            ShowError(new InvalidOperationException("Select at least one chapter for Video export."));
            return;
        }
        if (project.Metadata.ArtworkPath is null)
        {
            ShowError(new InvalidOperationException("Add project artwork in Audio before using Video."));
            return;
        }
        var path = await PickSaveAsync("MP4 video", ".mp4");
        if (path is null) return;
        await WorkAsync("Exporting MP4 video…", async () =>
            Status.Message = $"Exported {Path.GetFileName(await engine.ExportVideoAsync(project, path))}.");
    }

    private void VideoSelectAll_Click(object sender, RoutedEventArgs e)
    {
        foreach (var item in videoChapters) item.Selected = true;
        RefreshVideoChapters();
    }

    private void VideoSelectNone_Click(object sender, RoutedEventArgs e)
    {
        foreach (var item in videoChapters) item.Selected = false;
        RefreshVideoChapters();
    }

    private void VideoSelection_Click(object sender, RoutedEventArgs e) { RefreshVideoChapters(); MarkDirty(); }
    private void VideoSetting_Click(object sender, RoutedEventArgs e) { ApplyVideoEdits(); RefreshVideoPreviewTransform(); MarkDirty(); }
    private void VideoSettingSelection_Changed(object sender, SelectionChangedEventArgs e) { ApplyVideoEdits(); RefreshVideoPreviewTransform(); MarkDirty(); }
    private void VideoSettingNumber_Changed(NumberBox sender, NumberBoxValueChangedEventArgs e) { ApplyVideoEdits(); RefreshVideoPreviewTransform(); MarkDirty(); }

    private void VideoChapterDrag_Completed(ListViewBase sender, DragItemsCompletedEventArgs args)
    {
        videoChapters = sender.Items.Cast<VideoChapterItem>().ToList();
        RefreshVideoChapters();
        MarkDirty();
    }

    private void VideoChapter_DoubleTapped(object sender, Microsoft.UI.Xaml.Input.DoubleTappedRoutedEventArgs e)
    {
        if (VideoChapterList.SelectedItem is not VideoChapterItem item || !item.Selected) return;
        var index = SelectedVideoChapters().IndexOf(item);
        if (index >= 0) LoadVideoPreview(index, 0, false);
    }

    private void VideoPreviewPlay_Click(object sender, RoutedEventArgs e)
    {
        if (VideoPreviewPlayer.MediaPlayer.PlaybackSession.PlaybackState == MediaPlaybackState.Playing)
        {
            VideoPreviewPlayer.MediaPlayer.Pause();
            VideoPreviewPlay.Content = "Play";
            return;
        }
        if (SelectedVideoChapters().Count == 0) return;
        if (VideoPreviewPlayer.MediaPlayer.Source is null) LoadVideoPreview(videoPreviewIndex, 0, true);
        else VideoPreviewPlayer.MediaPlayer.Play();
        VideoPreviewPlay.Content = "Pause";
    }

    private void VideoPreviewPrevious_Click(object sender, RoutedEventArgs e) =>
        LoadVideoPreview(Math.Max(0, videoPreviewIndex - 1), 0, true);

    private void VideoPreviewNext_Click(object sender, RoutedEventArgs e) =>
        LoadVideoPreview(Math.Min(Math.Max(0, SelectedVideoChapters().Count - 1), videoPreviewIndex + 1), 0, true);

    private void VideoPreviewSeek_Changed(object sender, RangeBaseValueChangedEventArgs e)
    {
        if (updatingVideoPreviewSeek || project is null) return;
        var chapters = SelectedVideoChapters();
        if (chapters.Count == 0) return;
        var target = Math.Clamp(e.NewValue, 0, chapters.Sum(item => item.Chapter.DurationSeconds));
        var index = chapters.FindLastIndex(item => item.StartSeconds <= target);
        if (index < 0) index = 0;
        var playing = VideoPreviewPlayer.MediaPlayer.PlaybackSession.PlaybackState == MediaPlaybackState.Playing;
        LoadVideoPreview(index, Math.Max(0, target - chapters[index].StartSeconds), playing);
    }

    private void VideoPreviewMedia_Opened(MediaPlayer sender, object args)
    {
        sender.PlaybackSession.Position = TimeSpan.FromSeconds(pendingVideoPreviewSeconds);
        if (resumeVideoPreview) sender.Play();
        DispatcherQueue.TryEnqueue(() => VideoPreviewPlay.Content = resumeVideoPreview ? "Pause" : "Play");
    }

    private void VideoPreviewMedia_Ended(MediaPlayer sender, object args)
    {
        DispatcherQueue.TryEnqueue(() =>
        {
            if (videoPreviewIndex + 1 < SelectedVideoChapters().Count)
                LoadVideoPreview(videoPreviewIndex + 1, 0, true);
            else
            {
                VideoPreviewPlay.Content = "Play";
                UpdateVideoPreviewPosition();
            }
        });
    }

    private void VideoPreviewTimer_Tick(object? sender, object e) => UpdateVideoPreviewPosition();

    private List<VideoChapterItem> SelectedVideoChapters() => videoChapters.Where(item => item.Selected).ToList();

    private void LoadVideoPreview(int index, double withinChapter, bool play)
    {
        if (project is null) return;
        var chapters = SelectedVideoChapters();
        if (chapters.Count == 0)
        {
            VideoPreviewPlayer.MediaPlayer.Source = null;
            VideoPreviewBackground.Source = null;
            VideoPreviewForeground.Source = null;
            VideoPreviewPlay.Content = "Play";
            return;
        }
        videoPreviewIndex = Math.Clamp(index, 0, chapters.Count - 1);
        var item = chapters[videoPreviewIndex];
        var sourceIndex = item.Chapter.ChapterNumber - 1;
        if (sourceIndex < 0 || sourceIndex >= project.AudioSources.Count) return;
        pendingVideoPreviewSeconds = Math.Clamp(withinChapter, 0, item.Chapter.DurationSeconds);
        resumeVideoPreview = play;
        VideoPreviewPlayer.MediaPlayer.Source = MediaSource.CreateFromUri(new Uri(project.AudioSources[sourceIndex].SourcePath));
        var artwork = item.ArtworkUri is null ? null : new BitmapImage(new Uri(item.ArtworkUri));
        VideoPreviewBackground.Source = artwork;
        VideoPreviewForeground.Source = artwork;
        RefreshVideoPreviewTransform();
        UpdateVideoPreviewPosition();
    }

    private void RefreshVideoPreviewTransform()
    {
        if (project is null) return;
        var settings = project.Video.ExportSettings;
        var ratio = Math.Max(0.01, (double)settings.Width / Math.Max(1, settings.Height));
        if (ratio >= 1) { VideoPreviewCanvas.Width = 520; VideoPreviewCanvas.Height = 520 / ratio; }
        else { VideoPreviewCanvas.Height = 360; VideoPreviewCanvas.Width = 360 * ratio; }
        var transform = new ScaleTransform
        {
            ScaleX = settings.FlipHorizontal ? -1 : 1,
            ScaleY = settings.FlipVertical ? -1 : 1,
            CenterX = VideoPreviewCanvas.Width / 2,
            CenterY = VideoPreviewCanvas.Height / 2
        };
        VideoPreviewBackground.RenderTransform = transform;
        VideoPreviewForeground.RenderTransform = new ScaleTransform
        {
            ScaleX = transform.ScaleX,
            ScaleY = transform.ScaleY,
            CenterX = transform.CenterX,
            CenterY = transform.CenterY
        };
    }

    private void UpdateVideoPreviewPosition()
    {
        var chapters = SelectedVideoChapters();
        if (chapters.Count == 0)
        {
            updatingVideoPreviewSeek = true;
            VideoPreviewSeek.Maximum = 1;
            VideoPreviewSeek.Value = 0;
            updatingVideoPreviewSeek = false;
            VideoPreviewTime.Text = "00:00 / 00:00";
            return;
        }
        videoPreviewIndex = Math.Clamp(videoPreviewIndex, 0, chapters.Count - 1);
        var total = chapters.Sum(item => item.Chapter.DurationSeconds);
        var current = Math.Min(total, chapters[videoPreviewIndex].StartSeconds + VideoPreviewPlayer.MediaPlayer.PlaybackSession.Position.TotalSeconds);
        updatingVideoPreviewSeek = true;
        VideoPreviewSeek.Maximum = Math.Max(0.001, total);
        VideoPreviewSeek.Value = current;
        updatingVideoPreviewSeek = false;
        VideoPreviewTime.Text = $"{TimeSpan.FromSeconds(current):mm\\:ss} / {TimeSpan.FromSeconds(total):mm\\:ss}";
    }

    private void VideoMoveUp_Click(object sender, RoutedEventArgs e) => MoveVideoChapter(-1);
    private void VideoMoveDown_Click(object sender, RoutedEventArgs e) => MoveVideoChapter(1);

    private void MoveVideoChapter(int direction)
    {
        if (VideoChapterList.SelectedItem is not VideoChapterItem selected) return;
        var selectedItems = videoChapters.Where(item => item.Selected).ToList();
        var index = selectedItems.IndexOf(selected);
        var target = index + direction;
        if (index < 0 || target < 0 || target >= selectedItems.Count) return;
        selectedItems.RemoveAt(index);
        selectedItems.Insert(target, selected);
        var unselected = videoChapters.Where(item => !item.Selected).ToList();
        videoChapters = [.. selectedItems, .. unselected];
        RefreshVideoChapters();
        MarkDirty();
    }

    private void VideoPreset_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (isPresentingProject || VideoPresetPicker.SelectedItem is not VideoPreset preset || project is null) return;
        project.Video.ExportSettings.Platform = preset.Platform;
        project.Video.ExportSettings.Aspect = preset.Aspect;
        project.Video.ExportSettings.Width = preset.Width;
        project.Video.ExportSettings.Height = preset.Height;
        project.Video.ExportSettings.Fps = preset.Fps;
        VideoWidth.Value = preset.Width;
        VideoHeight.Value = preset.Height;
        VideoFps.Value = preset.Fps;
        RefreshVideoPreviewTransform();
        MarkDirty();
    }

    private async void Artwork_Click(object sender, RoutedEventArgs e)
    {
        if (project is null) return;
        var picker = new FileOpenPicker();
        InitializeWithWindow.Initialize(picker, WindowNative.GetWindowHandle(this));
        foreach (var extension in new[] { ".png", ".jpg", ".jpeg", ".webp" }) picker.FileTypeFilter.Add(extension);
        var file = await picker.PickSingleFileAsync();
        if (file is null) return;
        project.Metadata.ArtworkPath = file.Path;
        ArtworkName.Text = file.Name;
        foreach (var item in videoChapters.Where(item => item.Chapter.ImagePath is null)) item.ArtworkPath = file.Path;
        RefreshVideoChapters();
        MarkDirty();
    }

    private async void ChapterArtwork_Click(object sender, RoutedEventArgs e)
    {
        if (project is null || sender is not Button { DataContext: Chapter chapter }) return;
        var picker = new FileOpenPicker();
        InitializeWithWindow.Initialize(picker, WindowNative.GetWindowHandle(this));
        foreach (var extension in new[] { ".png", ".jpg", ".jpeg", ".webp" }) picker.FileTypeFilter.Add(extension);
        var file = await picker.PickSingleFileAsync();
        if (file is null) return;
        chapter.ImagePath = file.Path;
        var item = videoChapters.FirstOrDefault(candidate => candidate.Chapter.Id == chapter.Id);
        if (item is not null) item.ArtworkPath = file.Path;
        RefreshVideoChapters();
        MarkDirty();
    }

    private void AddChapter_Click(object sender, RoutedEventArgs e)
    {
        if (project is null) return;
        var number = project.Chapters.Count + 1;
        project.Chapters.Add(new Chapter
        {
            ChapterNumber = number,
            StartTimeSeconds = project.Chapters.Sum(chapter => chapter.DurationSeconds),
            DurationSeconds = 5,
            Title = $"Chapter {number}"
        });
        RefreshChapters();
        MarkDirty();
    }

    private void RemoveChapter_Click(object sender, RoutedEventArgs e)
    {
        if (project is null || ChapterList.SelectedItem is not Chapter chapter) return;
        project.Chapters.Remove(chapter);
        RefreshChapters();
        MarkDirty();
    }

    private async void ExportText_Click(object sender, RoutedEventArgs e) => await ExportTranscriptAsync("Plain text", ".txt", "txt");
    private async void ExportSrt_Click(object sender, RoutedEventArgs e) => await ExportTranscriptAsync("SubRip captions", ".srt", "srt");

    private async Task ExportTranscriptAsync(string label, string extension, string format)
    {
        if (project is null || project.TranscriptSegments.Count == 0) return;
        var path = await PickSaveAsync(label, extension);
        if (path is null) return;
        await WorkAsync("Exporting transcript…", async () =>
            Status.Message = $"Exported {Path.GetFileName(await engine.ExportTranscriptAsync(project, path, format))}.");
    }

    private async void ManageModels_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var models = await engine.ModelsAsync();
            var content = new StackPanel { Spacing = 12, MinWidth = 560 };
            content.Children.Add(new TextBlock
            {
                Text = "Models come from EnCap's pinned catalog, are verified with SHA-256, and run locally.",
                TextWrapping = TextWrapping.Wrap
            });
            foreach (var model in models)
            {
                var row = new Grid { ColumnSpacing = 12 };
                row.ColumnDefinitions.Add(new ColumnDefinition());
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
                var description = new StackPanel { Spacing = 2 };
                description.Children.Add(new TextBlock { Text = model.Name, FontWeight = Microsoft.UI.Text.FontWeights.SemiBold });
                description.Children.Add(new TextBlock { Text = $"{model.DownloadSize} · {model.Languages}" });
                description.Children.Add(new TextBlock { Text = model.Description, TextWrapping = TextWrapping.Wrap, Opacity = 0.75 });
                var action = new Button { Content = model.Installed ? "Remove" : "Download", VerticalAlignment = VerticalAlignment.Center };
                action.IsEnabled = model.Installed || model.DownloadAllowed;
                if (!model.Installed && !model.DownloadAllowed)
                    ToolTipService.SetToolTip(action, "EnCap is reusing a compatible model already installed by another app.");
                action.Click += async (_, _) =>
                {
                    action.IsEnabled = false;
                    try
                    {
                        if (model.Installed) await engine.RemoveModelAsync(model.Id);
                        else await engine.InstallModelAsync(model.Id);
                        action.Content = model.Installed ? "Download" : "Installed";
                        await LoadProvidersAsync();
                    }
                    catch (Exception error) { ShowError(error); action.IsEnabled = true; }
                };
                row.Children.Add(description);
                Grid.SetColumn(action, 1);
                row.Children.Add(action);
                content.Children.Add(row);
            }
            var dialog = new ContentDialog
            {
                Title = "Local transcription models",
                Content = new ScrollViewer { Content = content, MaxHeight = 520 },
                CloseButtonText = "Done",
                XamlRoot = Content.XamlRoot
            };
            await dialog.ShowAsync();
        }
        catch (Exception error) { ShowError(error); }
    }

    private async Task<string?> PickSaveAsync(string label, string extension)
    {
        var picker = new FileSavePicker { SuggestedFileName = project?.Metadata.EpisodeTitle ?? "EnCap" };
        InitializeWithWindow.Initialize(picker, WindowNative.GetWindowHandle(this));
        picker.FileTypeChoices.Add(label, [extension]);
        return (await picker.PickSaveFileAsync())?.Path;
    }

    private void PresentProject()
    {
        if (project is null) return;
        isPresentingProject = true;
        PodcastTitle.Text = project.Metadata.PodcastTitle;
        EpisodeTitle.Text = project.Metadata.EpisodeTitle;
        Summary.Text = project.Metadata.Summary;
        ArtworkName.Text = project.Metadata.ArtworkPath is null ? "No artwork selected" : Path.GetFileName(project.Metadata.ArtworkPath);
        ChapterList.ItemsSource = project.Chapters;
        TranscriptList.ItemsSource = project.TranscriptSegments;
        var video = project.Video.ExportSettings;
        VideoPresetPicker.SelectedItem = videoPresets.FirstOrDefault(preset =>
            preset.Platform == video.Platform && preset.Aspect == video.Aspect
            && preset.Width == video.Width && preset.Height == video.Height);
        VideoCodec.SelectedIndex = video.Codec == "hevc" ? 1 : 0;
        VideoEncoding.SelectedIndex = Math.Max(0, new[] { "automatic", "hardware", "software" }.ToList().IndexOf(video.Encoding));
        VideoFps.Value = video.Fps;
        VideoWidth.Value = video.Width;
        VideoHeight.Value = video.Height;
        VideoAudioBitrate.SelectedIndex = Math.Max(0, new[] { "64k", "96k", "128k", "160k", "192k", "256k", "320k" }.ToList().IndexOf(video.AudioBitrate));
        VideoFlipHorizontal.IsChecked = video.FlipHorizontal;
        VideoFlipVertical.IsChecked = video.FlipVertical;
        VideoPreviewQuality.SelectedIndex = Math.Max(0, new[] { "automatic", "low", "medium", "high" }.ToList().IndexOf(video.PreviewQuality));
        var selected = project.Video.ExportSettings.SelectedChapterIds;
        var ordered = selected.Select(id => project.Chapters.FirstOrDefault(chapter => chapter.Id == id)).Where(chapter => chapter is not null).Cast<Chapter>().ToList();
        ordered.AddRange(project.Chapters.Where(chapter => ordered.All(item => item.Id != chapter.Id)));
        videoChapters = ordered.Select(chapter => new VideoChapterItem
        {
            Chapter = chapter,
            ArtworkPath = chapter.ImagePath ?? project.Metadata.ArtworkPath,
            Selected = !project.Video.ExportSettings.SelectionInitialized || selected.Contains(chapter.Id)
        }).ToList();
        RefreshVideoChapters();
        currentMode = project.ActiveMode is "audio" or "transcript" or "video" ? project.ActiveMode : "audio";
        SelectNavigationMode(currentMode);
        ShowMode(currentMode);
        isPresentingProject = false;
        LoadVideoPreview(0, 0, false);
        Status.Message = $"Loaded {project.AudioSources.Count} audio files.";
    }

    private void TextEdit_Changed(object sender, TextChangedEventArgs e) => MarkDirty();
    private void SelectionEdit_Changed(object sender, SelectionChangedEventArgs e) => MarkDirty();
    private void NumberEdit_Changed(NumberBox sender, NumberBoxValueChangedEventArgs e) => MarkDirty();

    private void MarkDirty()
    {
        if (project is null || isPresentingProject) return;
        isDirty = true;
        recoveryDelay?.Cancel();
        recoveryDelay?.Dispose();
        recoveryDelay = new CancellationTokenSource();
        _ = SaveRecoveryAfterDelayAsync(recoveryDelay.Token);
    }

    private async Task SaveRecoveryAfterDelayAsync(CancellationToken cancellation)
    {
        try
        {
            await Task.Delay(1000, cancellation);
            while (!Navigation.IsEnabled) await Task.Delay(500, cancellation);
            if (!isDirty || project is null) return;
            ReadProjectEdits();
            await engine.SaveRecoveryAsync(project);
        }
        catch (OperationCanceledException) { }
        catch (Exception error) { ShowError(error); }
    }

    private void RefreshChapters()
    {
        if (project is null) return;
        var start = 0.0;
        for (var index = 0; index < project.Chapters.Count; index++)
        {
            project.Chapters[index].ChapterNumber = index + 1;
            project.Chapters[index].StartTimeSeconds = start;
            start += project.Chapters[index].DurationSeconds;
        }
        ChapterList.ItemsSource = null;
        ChapterList.ItemsSource = project.Chapters;
    }

    private void ReadProjectEdits()
    {
        if (project is null) return;
        project.Metadata.PodcastTitle = PodcastTitle.Text;
        project.Metadata.EpisodeTitle = EpisodeTitle.Text;
        project.Metadata.Summary = Summary.Text;
        project.ExportSettings.OutputFormat = Format.SelectedItem?.ToString() ?? "mp3";
        project.ExportSettings.QualityPreset = Bitrate.SelectedItem?.ToString() ?? "320k";
        project.ExportSettings.Channels = Convert.ToInt32(Channels.SelectedItem ?? 2);
        ApplyVideoEdits();
    }

    private void ApplyVideoEdits()
    {
        if (project is null) return;
        project.Video.ExportSettings.SelectedChapterIds = videoChapters.Where(item => item.Selected).Select(item => item.Chapter.Id).ToList();
        project.Video.ExportSettings.SelectionInitialized = true;
        project.Video.ExportSettings.Codec = VideoCodec.SelectedItem?.ToString() ?? "h264";
        project.Video.ExportSettings.Encoding = VideoEncoding.SelectedItem?.ToString() ?? "automatic";
        project.Video.ExportSettings.Fps = double.IsNaN(VideoFps.Value) ? 30 : (int)VideoFps.Value;
        project.Video.ExportSettings.Width = double.IsNaN(VideoWidth.Value) ? 1920 : (int)VideoWidth.Value;
        project.Video.ExportSettings.Height = double.IsNaN(VideoHeight.Value) ? 1080 : (int)VideoHeight.Value;
        project.Video.ExportSettings.AudioBitrate = VideoAudioBitrate.SelectedItem?.ToString() ?? "128k";
        project.Video.ExportSettings.FlipHorizontal = VideoFlipHorizontal.IsChecked == true;
        project.Video.ExportSettings.FlipVertical = VideoFlipVertical.IsChecked == true;
        project.Video.ExportSettings.PreviewQuality = VideoPreviewQuality.SelectedItem?.ToString() ?? "automatic";
    }

    private void RefreshVideoChapters()
    {
        var elapsed = 0.0;
        foreach (var item in videoChapters.Where(item => item.Selected))
        {
            item.StartSeconds = elapsed;
            elapsed += item.Chapter.DurationSeconds;
        }
        VideoChapterList.ItemsSource = null;
        VideoChapterList.ItemsSource = videoChapters;
        VideoTotal.Text = $"Total selected duration: {TimeSpan.FromSeconds(elapsed):hh\\:mm\\:ss}";
        ApplyVideoEdits();
        if (!isPresentingProject) LoadVideoPreview(0, 0, false);
    }

    private async Task WorkAsync(string message, Func<Task> action)
    {
        Status.Severity = InfoBarSeverity.Informational; Status.Message = message; Navigation.IsEnabled = false; CancelOperation.Visibility = Visibility.Visible;
        try { await action(); }
        catch (Exception error) { ShowError(error); }
        finally { Navigation.IsEnabled = true; CancelOperation.Visibility = Visibility.Collapsed; }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        Status.Message = "Cancelling safely…";
        engine.CancelCurrentOperation();
    }

    private void ShowError(Exception error) { Status.Severity = InfoBarSeverity.Error; Status.Message = error.Message; }
    private async void Navigation_SelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        var mode = args.SelectedItemContainer?.Tag?.ToString() ?? "audio";
        if (isChangingMode || mode == currentMode)
        {
            ShowMode(currentMode);
            return;
        }
        if (project is null)
        {
            currentMode = mode;
            ShowMode(mode);
            return;
        }

        ReadProjectEdits();
        var previousMode = currentMode;
        project.ActiveMode = mode;
        if (!string.IsNullOrWhiteSpace(project.ProjectPath))
        {
            try
            {
                Navigation.IsEnabled = false;
                await engine.SaveAsync(project, project.ProjectPath);
                isDirty = false;
                await engine.ClearRecoveryAsync();
            }
            catch (Exception error)
            {
                project.ActiveMode = previousMode;
                RestoreNavigationMode(previousMode);
                ShowError(new InvalidOperationException($"Could not save before switching modes: {error.Message}", error));
                return;
            }
            finally { Navigation.IsEnabled = true; }
        }
        else if (isDirty)
        {
            var dialog = new ContentDialog
            {
                Title = "Save this project?",
                Content = "Saving keeps the complete Audio, Transcript, and Video project portable. You can continue temporarily without saving.",
                PrimaryButtonText = "Save Project",
                SecondaryButtonText = "Continue Without Saving",
                CloseButtonText = "Cancel",
                DefaultButton = ContentDialogButton.Primary,
                XamlRoot = Content.XamlRoot
            };
            var choice = await dialog.ShowAsync();
            if (choice == ContentDialogResult.Primary)
            {
                var path = await PickSaveAsync("EnCap project", ".encap");
                if (path is null || !await SaveForModeSwitchAsync(path, previousMode)) return;
            }
            else if (choice != ContentDialogResult.Secondary)
            {
                project.ActiveMode = previousMode;
                RestoreNavigationMode(previousMode);
                return;
            }
        }

        currentMode = mode;
        ShowMode(mode);
        if (string.IsNullOrWhiteSpace(project.ProjectPath)) MarkDirty();
    }

    private async Task<bool> SaveForModeSwitchAsync(string path, string previousMode)
    {
        if (project is null) return false;
        try
        {
            Navigation.IsEnabled = false;
            await engine.SaveAsync(project, path);
            project.ProjectPath = path;
            isDirty = false;
            await engine.ClearRecoveryAsync();
            return true;
        }
        catch (Exception error)
        {
            project.ActiveMode = previousMode;
            RestoreNavigationMode(previousMode);
            ShowError(new InvalidOperationException($"Could not save before switching modes: {error.Message}", error));
            return false;
        }
        finally { Navigation.IsEnabled = true; }
    }

    private void ShowMode(string mode)
    {
        AudioPanel.Visibility = mode == "audio" ? Visibility.Visible : Visibility.Collapsed;
        TranscriptPanel.Visibility = mode == "transcript" ? Visibility.Visible : Visibility.Collapsed;
        VideoPanel.Visibility = mode == "video" ? Visibility.Visible : Visibility.Collapsed;
    }

    private void SelectNavigationMode(string mode)
    {
        var item = Navigation.MenuItems.OfType<NavigationViewItem>()
            .FirstOrDefault(candidate => candidate.Tag?.ToString() == mode);
        if (item is not null) Navigation.SelectedItem = item;
    }

    private void RestoreNavigationMode(string mode)
    {
        isChangingMode = true;
        SelectNavigationMode(mode);
        isChangingMode = false;
        ShowMode(mode);
    }
}

public sealed class VideoChapterItem
{
    public Chapter Chapter { get; set; } = new();
    public string? ArtworkPath { get; set; }
    public bool Selected { get; set; }
    public double StartSeconds { get; set; }
    public string Title => Chapter.Title;
    public string? ArtworkUri => string.IsNullOrWhiteSpace(ArtworkPath) ? null : new Uri(ArtworkPath).AbsoluteUri;
    public string Timeline => $"{TimeSpan.FromSeconds(StartSeconds):mm\\:ss} · {TimeSpan.FromSeconds(Chapter.DurationSeconds):mm\\:ss}";
}
