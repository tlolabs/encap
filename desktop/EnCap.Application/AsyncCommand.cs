using System.Windows.Input;
namespace EnCap;

public sealed class AsyncCommand(Func<Task> action, Func<bool>? enabled = null) : ICommand
{
    public event EventHandler? CanExecuteChanged;
    private bool running;
    public bool CanExecute(object? parameter) => !running && (enabled?.Invoke() ?? true);
    public async void Execute(object? parameter) => await ExecuteAsync();
    public async Task ExecuteAsync()
    {
        if (!CanExecute(null))
            return;
        running = true;
        Refresh();
        try
        {
            await action();
        }
        finally { running = false; Refresh(); }
    }
    public void Refresh() => CanExecuteChanged?.Invoke(this, EventArgs.Empty);
}
