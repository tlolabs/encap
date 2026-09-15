using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Shapes;

namespace EnCap;

public sealed class SourceWaveform : UserControl
{
    private readonly Canvas surface = new();
    public static readonly DependencyProperty PeaksProperty = DependencyProperty.Register(
        nameof(Peaks), typeof(double[]), typeof(SourceWaveform), new PropertyMetadata(null, (sender, _) => ((SourceWaveform)sender).Draw()));
    public double[]? Peaks { get => (double[]?)GetValue(PeaksProperty); set => SetValue(PeaksProperty, value); }
    public SourceWaveform()
    {
        Height = 12; IsHitTestVisible = false; IsTabStop = false;
        Content = surface;
        SizeChanged += (_, _) => Draw();
        RegisterPropertyChangedCallback(ForegroundProperty, (_, _) => Draw());
    }
    private void Draw()
    {
        surface.Children.Clear();
        double width = ActualWidth;
        if (width < 3) return;
        int count = Math.Min(64, Math.Max(1, (int)(width / 3)));
        double step = width / count;
        var values = Peaks ?? [];
        if (values.Length != 64) return;
        var geometry = new GeometryGroup();
        for (int bar = 0; bar < count; bar++) {
            double peak = 0;
            for (int sample = values.Length * bar / count; sample < values.Length * (bar + 1) / count; sample++) peak = Math.Max(peak, values[sample]);
            double height = Math.Max(1, 12 * Math.Clamp(peak, 0, 1));
            geometry.Children.Add(new RectangleGeometry { Rect = new Windows.Foundation.Rect(bar * step, 12 - height, Math.Max(1, step - 1), height) });
        }
        surface.Children.Add(new Microsoft.UI.Xaml.Shapes.Path { Data = geometry, Fill = Foreground });
    }
}
