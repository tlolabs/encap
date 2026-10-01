namespace EnCap;

public interface IApplicationUpdates
{
    bool Automatic
    {
        get; set;
    }
    Task CheckAsync(bool manual);
}
