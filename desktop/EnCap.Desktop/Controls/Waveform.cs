using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
namespace EnCap;

public sealed class Waveform : Control
{
    public static readonly StyledProperty<double[]?> PeaksProperty = AvaloniaProperty.Register<Waveform, double[]?>(nameof(Peaks));
    public double[]? Peaks
    {
        get => GetValue(PeaksProperty); set => SetValue(PeaksProperty, value);
    }
    static Waveform()
    {
        AffectsRender<Waveform>(PeaksProperty);
    }
    public override void Render(DrawingContext context)
    {
        base.Render(context);
        var values = Peaks;
        if (values is null || values.Length == 0)
            return;
        var width = Bounds.Width / values.Length;
        for (int i = 0; i < values.Length; i++)
        {
            var h = Math.Max(1, Bounds.Height * Math.Clamp(values[i], 0, 1));
            context.FillRectangle(Brushes.SteelBlue, new Rect(i * width, (Bounds.Height - h) / 2, Math.Max(1, width - 1), h));
        }
    }
}
