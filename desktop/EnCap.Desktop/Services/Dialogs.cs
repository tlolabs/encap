using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Platform.Storage;
namespace EnCap;

public sealed class Dialogs(Window owner) : IUserDialogs
{
    public async Task<string?> FolderAsync() => (await owner.StorageProvider.OpenFolderPickerAsync(new() { Title = "Import recordings", AllowMultiple = false })).FirstOrDefault()?.TryGetLocalPath();
    public async Task<string[]> OpenAsync(string title, string[] extensions, bool multiple = false) => (await owner.StorageProvider.OpenFilePickerAsync(new() { Title = title, AllowMultiple = multiple, FileTypeFilter = [new(title) { Patterns = extensions.Select(e => "*." + e).ToArray() }] })).Select(f => f.TryGetLocalPath()).OfType<string>().ToArray();
    public async Task<string?> SaveAsync(string title, string extension, string suggestedName) => (await owner.StorageProvider.SaveFilePickerAsync(new() { Title = title, SuggestedFileName = string.IsNullOrWhiteSpace(suggestedName) ? "EnCap" : suggestedName, DefaultExtension = extension, FileTypeChoices = [new(title) { Patterns = ["*." + extension] }], ShowOverwritePrompt = true }))?.TryGetLocalPath();
    public async Task<bool> ConfirmAsync(string title, string message) => await AskAsync(title, message, ["Continue", "Cancel"]) == 0;
    public async Task<SaveChoice> UnsavedAsync(bool replacing = true) => await AskAsync("Save changes?", "Save your project before continuing. Original recordings are never removed.", ["Save Project", replacing ? "Discard Changes" : "Continue Without Saving", "Cancel"]) switch { 0 => SaveChoice.Save, 1 => SaveChoice.Discard, _ => SaveChoice.Cancel };
    private async Task<int> AskAsync(string title, string message, string[] choices)
    {
        var dialog = new Window { Title = title, Width = 480, SizeToContent = SizeToContent.Height, CanResize = false, WindowStartupLocation = WindowStartupLocation.CenterOwner };
        var panel = new StackPanel { Margin = new(24), Spacing = 16 };
        panel.Children.Add(new TextBlock { Text = message, TextWrapping = Avalonia.Media.TextWrapping.Wrap });
        var buttons = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8, HorizontalAlignment = HorizontalAlignment.Right };
        for (var i = 0; i < choices.Length; i++)
        {
            var index = i;
            var button = new Button { Content = choices[i], IsCancel = i == choices.Length - 1, IsDefault = i == choices.Length - 1 };
            button.Click += (_, _) => dialog.Close(index);
            buttons.Children.Add(button);
        }
        panel.Children.Add(buttons);
        dialog.Content = panel;
        return await dialog.ShowDialog<int?>(owner) ?? choices.Length - 1;
    }
}
