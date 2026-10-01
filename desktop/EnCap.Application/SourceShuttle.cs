namespace EnCap;

public static class SourceShuttle
{
    public static double Rate(double current, int direction, bool slow = false) =>
        slow ? direction * 0.5 : direction * (current * direction > 0 ? Math.Min(32, Math.Max(1, Math.Abs(current) * 2)) : 1);
}
