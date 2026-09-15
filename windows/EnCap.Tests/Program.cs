using EnCap;
using System.Text.Json;

if (args.Length != 1) throw new ArgumentException("Pass the shared chapter timestamp fixture path.");
var count = 0;
foreach (var line in File.ReadLines(args[0])) {
    if (string.IsNullOrWhiteSpace(line) || line.StartsWith('#')) continue;
    var parts = line.Split('\t');
    var expected = parts[1] == "-" ? null : parts[1];
    if (ChapterNaming.RoundedTime(parts[0]) != expected) throw new Exception($"Timestamp mismatch: {parts[0]}");
    count++;
}
if (count == 0) throw new Exception("No timestamp cases ran.");
var project = new ProjectDocument {
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

void AssertTitles(params string[] titles) {
    if (!project.Chapters.Select(c => c.Title).SequenceEqual(titles)) throw new Exception("Unexpected chapter titles.");
}

foreach (var line in File.ReadLines(Path.Combine(Path.GetDirectoryName(args[0])!, "source-shuttle.tsv")).Where(line => !line.StartsWith('#') && line.Length > 0)) {
    var values = line.Split(' ', StringSplitOptions.RemoveEmptyEntries).Select(value => double.Parse(value, System.Globalization.CultureInfo.InvariantCulture)).ToArray();
    if (SourceShuttle.Rate(values[0], (int)values[1], values[2] != 0) != values[3]) throw new Exception($"Shuttle mismatch: {line}");
}
Console.WriteLine("Passed shared shuttle playback cases.");
