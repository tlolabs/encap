using Avalonia.Data.Converters;
using Avalonia.Media.Imaging;
using System.Globalization;
namespace EnCap;

public sealed class LocalImageConverter : IValueConverter
{
    private readonly Dictionary<string, WeakReference<Bitmap>> cache = [];
    public object? Convert(object? value, Type targetType, object? parameter, CultureInfo culture)
    {
        if (value is not string path || !File.Exists(path))
            return null;
        if (cache.TryGetValue(path, out var weak) && weak.TryGetTarget(out var bitmap))
            return bitmap;
        try
        {
            if (cache.Count >= 64)
                cache.Clear();
            using var stream = File.OpenRead(path);
            var decoded = Bitmap.DecodeToWidth(stream, 1024);
            cache[path] = new(decoded);
            return decoded;
        }
        catch (IOException) { return null; }
        catch (ArgumentException) { return null; }
    }
    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) => throw new NotSupportedException();
}
