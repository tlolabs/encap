using System.Globalization;

namespace EnCap;

public enum ChapterNamingStyle { Original, Numbered, Time, Custom }

public static class ChapterNaming
{
    public static string? RoundedTime(string filename)
    {
        // DisplayName preserves the recorder filename after archives rename stored media.
        filename = filename.Replace('\\', '/').Split('/')[^1];
        if (filename.Length < 14 || !filename.AsSpan(0, 14).ToArray().All(c => c is >= '0' and <= '9')) return null;
        if (!DateTime.TryParseExact(filename[..14], "MMddyyyyHHmmss", CultureInfo.InvariantCulture,
            DateTimeStyles.None, out var recorded)) return null;
        var minutes = (recorded.Hour * 60 + recorded.Minute + (recorded.Second >= 30 ? 1 : 0)) % 1440;
        var hour = minutes / 60;
        return string.Format(CultureInfo.InvariantCulture, "{0}:{1:00} {2}", hour % 12 == 0 ? 12 : hour % 12, minutes % 60, hour < 12 ? "AM" : "PM");
    }

    public static void Apply(ProjectDocument project, ChapterNamingStyle style, ISet<string>? onlyChapterIds = null)
    {
        for (var index = 0; index < project.Chapters.Count; index++)
        {
            var chapter = project.Chapters[index];
            if (onlyChapterIds is not null && !onlyChapterIds.Contains(chapter.Id)) continue;
            var sourceIndex = chapter.ChapterNumber - 1;
            var source = sourceIndex >= 0 && sourceIndex < project.AudioSources.Count ? project.AudioSources[sourceIndex] : null;
            chapter.Title = style switch {
                ChapterNamingStyle.Numbered => $"Chapter {index + 1}",
                ChapterNamingStyle.Original when source is not null => source.DisplayName,
                ChapterNamingStyle.Time when source is not null => RoundedTime(source.DisplayName) ?? RoundedTime(source.SourcePath) ?? source.DisplayName,
                _ => chapter.Title
            };
        }
    }

    private static string PreferencePath => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "EnCap", "chapter-naming.txt");

    public static ChapterNamingStyle LoadPreference()
    {
        try {
            return Enum.TryParse<ChapterNamingStyle>(File.ReadAllText(PreferencePath).Trim(), out var style) && Enum.IsDefined(style)
                ? style : ChapterNamingStyle.Original;
        }
        catch (IOException) { return ChapterNamingStyle.Original; }
        catch (UnauthorizedAccessException) { return ChapterNamingStyle.Original; }
    }

    public static void SavePreference(ChapterNamingStyle style)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(PreferencePath)!);
        File.WriteAllText(PreferencePath, style.ToString());
    }
}
