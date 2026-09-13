using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
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

    public MainWindow()
    {
        InitializeComponent();
        Title = "EnCap";
        AppWindow.Resize(new Windows.Graphics.SizeInt32(1180, 820));
        _ = InitializeAsync();
    }

    private async Task InitializeAsync()
    {
        await LoadProvidersAsync();
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
        isPresentingProject = false;
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
    private void Navigation_SelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        var transcribe = args.SelectedItemContainer?.Tag?.ToString() == "transcribe";
        AssemblePanel.Visibility = transcribe ? Visibility.Collapsed : Visibility.Visible;
        TranscribePanel.Visibility = transcribe ? Visibility.Visible : Visibility.Collapsed;
    }
}
