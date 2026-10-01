namespace EnCap;

public static class AppIdentity
{
    // Avalonia on macOS is always internal, including an unpackaged developer run.
    public static bool IsReference => OperatingSystem.IsMacOS();
    public static string Title => IsReference ? "EnCap — INTERNAL Avalonia Reference" : "EnCap";
    public static string DataDirectory
    {
        get
        {
            var path = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), IsReference ? "com.tlolabs.encap.avalonia-reference" : "com.tlolabs.encap");
            Directory.CreateDirectory(path);
            return path;
        }
    }
    public static bool ProductionUpdatesAllowed => !IsReference && (OperatingSystem.IsWindows() || OperatingSystem.IsLinux());
}
