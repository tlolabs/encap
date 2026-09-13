using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Windows.Storage.Pickers;
using WinRT.Interop;

namespace EnCap;

public sealed partial class MainWindow : Window
{
    private readonly EngineClient engine = new();
    private ProjectDocument? project;

    public MainWindow()
    {
        InitializeComponent();
        Title = "EnCap";
        AppWindow.Resize(new Windows.Graphics.SizeInt32(1180, 820));
        _ = LoadProvidersAsync();
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
        await WorkAsync("Reading audio…", async () => { project = await engine.InspectAsync(folder.Path); PresentProject(); });
    }

    private async void Open_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker();
        InitializeWithWindow.Initialize(picker, WindowNative.GetWindowHandle(this));
        picker.FileTypeFilter.Add(".encap");
        var file = await picker.PickSingleFileAsync();
        if (file is null) return;
        await WorkAsync("Opening project…", async () => { project = await engine.OpenAsync(file.Path); PresentProject(); });
    }

    private async void Save_Click(object sender, RoutedEventArgs e)
    {
        if (project is null) return;
        var path = await PickSaveAsync("EnCap project", ".encap");
        if (path is null) return;
        ReadProjectEdits();
        await WorkAsync("Saving project…", async () => Status.Message = $"Saved {Path.GetFileName(await engine.SaveAsync(project, path))}." );
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
        await WorkAsync("Transcribing locally…", async () => { project.TranscriptSegments = await engine.TranscribeAsync(project, provider.Id); TranscriptList.ItemsSource = project.TranscriptSegments; });
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
        PodcastTitle.Text = project.Metadata.PodcastTitle;
        EpisodeTitle.Text = project.Metadata.EpisodeTitle;
        Summary.Text = project.Metadata.Summary;
        ChapterList.ItemsSource = project.Chapters;
        TranscriptList.ItemsSource = project.TranscriptSegments;
        Status.Message = $"Loaded {project.AudioSources.Count} audio files.";
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
        Status.Severity = InfoBarSeverity.Informational; Status.Message = message; Navigation.IsEnabled = false;
        try { await action(); }
        catch (Exception error) { ShowError(error); }
        finally { Navigation.IsEnabled = true; }
    }

    private void ShowError(Exception error) { Status.Severity = InfoBarSeverity.Error; Status.Message = error.Message; }
    private void Navigation_SelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        var transcribe = args.SelectedItemContainer?.Tag?.ToString() == "transcribe";
        AssemblePanel.Visibility = transcribe ? Visibility.Collapsed : Visibility.Visible;
        TranscribePanel.Visibility = transcribe ? Visibility.Visible : Visibility.Collapsed;
    }
}

