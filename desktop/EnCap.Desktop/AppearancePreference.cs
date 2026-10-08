using Avalonia.Styling;

namespace EnCap;

public static class AppearancePreference
{
    private static string PreferencePath => Path.Combine(AppIdentity.DataDirectory, "appearance.txt");

    public static ThemeVariant Load() => Load(PreferencePath);

    public static ThemeVariant Load(string path)
    {
        try { return Parse(File.ReadAllText(path)); }
        catch (IOException) { return ThemeVariant.Default; }
        catch (UnauthorizedAccessException) { return ThemeVariant.Default; }
    }

    public static ThemeVariant Parse(string? value) => value?.Trim().ToLowerInvariant() switch
    {
        "light" => ThemeVariant.Light,
        "dark" => ThemeVariant.Dark,
        _ => ThemeVariant.Default
    };

    public static void Save(ThemeVariant variant) => Save(PreferencePath, variant);

    public static void Save(string path, ThemeVariant variant)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, variant == ThemeVariant.Light ? "light" : variant == ThemeVariant.Dark ? "dark" : "system");
    }
}
