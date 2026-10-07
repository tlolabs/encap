using EnCap;
using System.Text.Json;
using Avalonia;
using Avalonia.Automation;
using Avalonia.Controls;
using Avalonia.Headless;
using Avalonia.Input;
using Avalonia.Styling;
using Avalonia.Threading;
using EnCap.Tests;

if (args.Length != 1 && args.Length != 4 && !(args.Length == 2 && args[1] == "--accessibility")) throw new ArgumentException("Pass the shared chapter timestamp fixture path.");
var count = 0;
foreach (var line in File.ReadLines(args[0]))
{
    if (string.IsNullOrWhiteSpace(line) || line.StartsWith('#'))
        continue;
    var parts = line.Split('\t');
    var expected = parts[1] == "-" ? null : parts[1];
    if (ChapterNaming.RoundedTime(parts[0]) != expected)
        throw new Exception($"Timestamp mismatch: {parts[0]}");
    count++;
}
if (count == 0) throw new Exception("No timestamp cases ran.");
var project = new ProjectDocument
{
    AudioSources = [new AudioSource { SourcePath = "/session/audio/001-09082026061816_DN-700R.wav", DisplayName = "09082026061816_DN-700R", DurationSeconds = 60 }],
    Chapters = [
        new Chapter { Id = "a", ChapterNumber = 1, Title = "Custom. Name", DurationSeconds = 30, LinkUrl = "https://example.com", ImagePath = "/cover.png" },
        new Chapter { Id = "b", ChapterNumber = 1, Title = "Closing", StartTimeSeconds = 30, DurationSeconds = 30 },
        new Chapter { Id = "c", ChapterNumber = 99, Title = "Manual", StartTimeSeconds = 60, DurationSeconds = 5 }
    ]
};
var before = JsonSerializer.Serialize(project);
ChapterNaming.Apply(project, ChapterNamingStyle.Custom);
if (before != JsonSerializer.Serialize(project)) throw new Exception("Custom changed existing titles.");
ChapterNaming.Apply(project, ChapterNamingStyle.Time, new HashSet<string> { "b" });
AssertTitles("Custom. Name", "6:18 AM", "Manual");
ChapterNaming.Apply(project, ChapterNamingStyle.Original);
AssertTitles("09082026061816_DN-700R", "09082026061816_DN-700R", "Manual");
ChapterNaming.Apply(project, ChapterNamingStyle.Numbered);
AssertTitles("Chapter 1", "Chapter 2", "Chapter 3");
if (project.Chapters[1].ChapterNumber != 1 || project.Chapters[0].ImagePath != "/cover.png" || project.Chapters[0].LinkUrl != "https://example.com")
    throw new Exception("Naming changed chapter metadata or source references.");
var reopened = JsonSerializer.Deserialize<ProjectDocument>(JsonSerializer.Serialize(project))!;
if (!reopened.Chapters.Select(c => c.Title).SequenceEqual(project.Chapters.Select(c => c.Title))) throw new Exception("Names did not survive serialization.");
Console.WriteLine($"Passed {count} shared timestamp cases and chapter naming/preservation checks.");

void AssertTitles(params string[] titles)
{
    if (!project.Chapters.Select(c => c.Title).SequenceEqual(titles))
        throw new Exception("Unexpected chapter titles.");
}

foreach (var line in File.ReadLines(Path.Combine(Path.GetDirectoryName(args[0])!, "source-shuttle.tsv")).Where(line => !line.StartsWith('#') && line.Length > 0))
{
    var values = line.Split(' ', StringSplitOptions.RemoveEmptyEntries).Select(value => double.Parse(value, System.Globalization.CultureInfo.InvariantCulture)).ToArray();
    if (SourceShuttle.Rate(values[0], (int)values[1], values[2] != 0) != values[3])
        throw new Exception($"Shuttle mismatch: {line}");
}
Console.WriteLine("Passed shared shuttle playback cases.");

var checks = 0;
if (args.Length == 2)
{
    var appearancePath = Path.Combine(Path.GetTempPath(), "encap-appearance-" + Guid.NewGuid(), "appearance.txt");
    try
    {
        Check(AppearancePreference.Load(appearancePath) == ThemeVariant.Default, "Appearance defaults to System");
        AppearancePreference.Save(appearancePath, ThemeVariant.Dark);
        Check(AppearancePreference.Load(appearancePath) == ThemeVariant.Dark, "Dark appearance survives restart");
        AppearancePreference.Save(appearancePath, ThemeVariant.Light);
        Check(AppearancePreference.Load(appearancePath) == ThemeVariant.Light, "Light appearance survives restart");
        AppearancePreference.Save(appearancePath, ThemeVariant.Default);
        Check(AppearancePreference.Load(appearancePath) == ThemeVariant.Default, "System appearance survives restart");
    }
    finally { Directory.Delete(Path.GetDirectoryName(appearancePath)!, recursive: true); }
    await using var accessibilitySession = HeadlessUnitTestSession.StartNew(typeof(TestApp));
    await accessibilitySession.Dispatch(() =>
    {
        var window = new MainWindow(new FakeEngine(), new FakeDialogs(), new FakePlayback());
        Check(AutomationProperties.GetLiveSetting(window.FindControl<TextBlock>("StatusText")!) == AutomationLiveSetting.Polite, "Status is a polite live region");
        Check(AutomationProperties.GetName(window.FindControl<ProgressBar>("OperationProgress")!) == "Operation in progress", "Progress has an accessible name");
        Check(AutomationProperties.GetName(window.FindControl<Slider>("SourceSeek")!) == "Recording position", "Audio seek has an accessible name");
        Check(AutomationProperties.GetName(window.FindControl<Slider>("VideoSeek")!) == "Video timeline position", "Video seek has an accessible name");
        Check(new[] { "ThemeSystemMenu", "ThemeLightMenu", "ThemeDarkMenu" }.Count(name => window.FindControl<MenuItem>(name)!.IsChecked) == 1, "Exactly one appearance option is selected");
        var expectedModifier = OperatingSystem.IsMacOS() ? KeyModifiers.Meta : KeyModifiers.Control;
        Check(window.KeyBindings.All(binding => (binding.Gesture?.KeyModifiers & expectedModifier) == expectedModifier), "Shortcuts use the host platform modifier");
        Check((window.FindControl<MenuItem>("OpenMenu")!.InputGesture?.KeyModifiers & expectedModifier) == expectedModifier, "Menu displays the host platform shortcut");
        window.Editor.Dispose();
        return true;
    }, CancellationToken.None);
    Console.WriteLine($"Passed {checks} informational accessibility checks.");
    return;
}
var options = new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
var roundTrip = JsonSerializer.Deserialize<ProjectDocument>("""{"future_field":{"enabled":true},"metadata":{"future_metadata":42},"chapters":[{"future_chapter":"retained"}]}""", options)!;
var encoded = JsonDocument.Parse(JsonSerializer.Serialize(roundTrip, options)).RootElement;
Check(encoded.GetProperty("future_field").GetProperty("enabled").GetBoolean(), "Unknown project fields survive");
Check(encoded.GetProperty("metadata").GetProperty("future_metadata").GetInt32() == 42, "Unknown metadata survives");
Check(encoded.GetProperty("chapters")[0].GetProperty("future_chapter").GetString() == "retained", "Unknown chapter fields survive");
Check(!encoded.GetProperty("chapters")[0].TryGetProperty("display_number", out _), "UI-only fields excluded");
if (args.Length == 4) await EngineIntegration.RunAsync(args[1], args[2], args[3]);
await using var session = HeadlessUnitTestSession.StartNew(typeof(TestApp));
await session.Dispatch(async () =>
{
    var engine = new FakeEngine();
    var dialogs = new FakeDialogs();
    var playback = new FakePlayback();
    var window = new MainWindow(engine, dialogs, playback);
    window.Show();
    var vm = window.Editor;
    if (AppIdentity.IsReference)
    {
        bool blocked = false;
        try
        {
            await UpdateService.RunAsync("check");
        }
        catch (InvalidOperationException) { blocked = true; }
        Check(blocked, "Internal reference refuses production updater execution");
    }
    Check(!vm.SaveCommand.CanExecute(null), "Save unavailable without project");
    await vm.ImportCommand.ExecuteAsync();
    Check(vm.HasProject && vm.Sources.Count == 2 && vm.Chapters.Count == 2 && vm.IsDirty, "Import presentation");
    Check(window.FindControl<ListBox>("SourceList")!.ItemCount == 2, "Source list binding");
    vm.SelectedSources.Add(vm.Sources[1]);
    vm.SelectedSources.Add(vm.Sources[0]);
    Check(vm.SelectedSource == vm.Sources[0], "Multi-selection plays first displayed recording");
    vm.SelectedSources.Clear();
    var realDialogs = new Dialogs(window);
    var unsaved = realDialogs.UnsavedAsync();
    window.OwnedWindows.Single().Close();
    Check(await unsaved == SaveChoice.Cancel, "Dismissing unsaved dialog cancels");

    window.FindControl<TextBox>("EpisodeTitle")!.Text = "Edited title";
    Dispatcher.UIThread.RunJobs();
    Check(vm.Project!.Metadata.EpisodeTitle == "Edited title", "AXAML two-way title editing");
    vm.Project.ExportSettings.Encoder = "lame";
    vm.Project.ExportSettings.OutputFormat = "aac";
    Check(vm.Project.ExportSettings.Encoder == "ffmpeg", "Format change selects compatible encoder");
    var titleBox = window.FindControl<TextBox>("EpisodeTitle")!;
    titleBox.Focus();
    titleBox.SelectAll();
    window.KeyTextInput("Keyboard title");
    Dispatcher.UIThread.RunJobs();
    Check(vm.Project.Metadata.EpisodeTitle == "Keyboard title", "Keyboard text editing");
    dialogs.Destination = null;
    Check(!await vm.SaveAsync(true) && vm.IsDirty, "Save dialog cancellation retains edits");
    dialogs.Destination = "/saved.encap";
    engine.ThrowSave = true;
    await vm.SaveCommand.ExecuteAsync();
    Check(vm.IsDirty && vm.HasError && vm.Status == "Disk full", "Save failure preserves state and reports error");
    engine.ThrowSave = false;
    await vm.SaveCommand.ExecuteAsync();
    Check(!vm.IsDirty && engine.Saved == 1, "Save clears dirty state after success");
    vm.Project.Metadata.Summary = "Unsaved";
    Check(!await vm.CanCloseAsync(), "Cancel close preserves work");
    window.Close();
    Check(window.IsVisible, "Window close cancellation retains editor");
    vm.SelectedSource = vm.Sources[0];
    await vm.TogglePlaybackAsync();
    playback.Seek(3);
    vm.Pause();
    await vm.TogglePlaybackAsync();
    Check(playback.Opens == 1 && playback.Position == 3 && playback.IsPlaying, "Recording pause/resume");
    await vm.ShuttleAsync(-1);
    Check(playback.Rate == -1, "Reverse shuttle");
    await vm.ShuttleAsync(-1);
    Check(playback.Rate == -2, "Repeated shuttle");
    await vm.ShuttleAsync(1, true);
    Check(playback.Rate == 0.5, "Half speed");
    vm.Present(FakeEngine.Fixture());
    vm.SelectedSource = vm.Sources[0];
    await vm.TogglePlaybackAsync();
    Check(playback.Opens == 2, "Replacement reopens closed media");
    await vm.SwitchModeAsync(2); // no saved path: cancel retains audio
    Check(vm.Mode == 0, "Cancelled mode transition retains mode");
    dialogs.Choice = SaveChoice.Discard;
    await vm.SwitchModeAsync(2);
    Check(vm.IsVideo, "Video mode transition");
    Check(vm.PreviewArtwork == "/cover.png", "Video artwork available before playback");
    vm.SelectedVideo = vm.VideoChapters[1];
    vm.MoveVideo(-1);
    Check(vm.Project!.Video.ExportSettings.SelectedChapterIds.SequenceEqual(new[] { "b", "a" }), "Video ordering persists");
    await vm.TogglePlaybackAsync();
    playback.Seek(4);
    vm.Pause();
    await vm.TogglePlaybackAsync();
    Check(playback.Position == 4, "Video pause/resume retains position");
    await vm.SeekAsync(23);
    Check(playback.Path == "/one.wav" && playback.Position == 3, "Video timeline seeks correct recording");
    await vm.SelectNoneCommand.ExecuteAsync();
    await vm.ExportVideoCommand.ExecuteAsync();
    Check(vm.HasError && engine.ExportKind is null, "Empty video selection rejected");
    await vm.SelectAllCommand.ExecuteAsync();
    await vm.ExportVideoCommand.ExecuteAsync();
    Check(engine.ExportKind == "video", "Video export routes to core");
    await vm.TranscribeCommand.ExecuteAsync();
    Check(vm.Segments.Count == 1, "Transcript presentation");
    vm.Segments[0].Text = "Correction";
    Check(vm.Project.TranscriptSegments[0].Text == "Correction" && vm.IsDirty, "Transcript editing");
    await vm.ExportTextCommand.ExecuteAsync();
    Check(engine.ExportKind == "txt", "Text export");
    await vm.ExportSrtCommand.ExecuteAsync();
    Check(engine.ExportKind == "srt", "SRT export");
    engine.PendingExport = new();
    var export = vm.ExportAudioCommand.ExecuteAsync();
    Check(vm.IsBusy && !vm.ImportCommand.CanExecute(null) && vm.CancelCommand.CanExecute(null), "Busy command gating");
    Check(!await vm.CanCloseAsync(), "Busy close blocked");
    await vm.CancelCommand.ExecuteAsync();
    await export;
    Check(engine.Cancelled && !vm.IsBusy, "Cancellation releases busy state");
    await Task.Delay(1100);
    Check(engine.Recovered > 0, "Debounced recovery");
    dialogs.Choice = SaveChoice.Discard;
    bool closed = false;
    window.Closed += (_, _) => closed = true;
    window.Close();
    Dispatcher.UIThread.RunJobs();
    Check(closed, "Confirmed close disposes editor");
    return true;
}, CancellationToken.None);
Console.WriteLine($"Passed {checks} presentation, lifecycle, serialization and headless UI checks.");

void Check(bool value, string label) { if (!value) throw new Exception(label); checks++; Console.WriteLine("PASS " + label); }

public static class TestApp
{
    public static AppBuilder BuildAvaloniaApp() => AppBuilder.Configure<App>().UseHeadless(new AvaloniaHeadlessPlatformOptions());
}
