using Microsoft.UI.Xaml.Controls;
using PrismCore.ViewModels;

namespace PrismCore.Views;

public sealed partial class ToolboxPage : Page
{
    public ToolboxViewModel ViewModel { get; } = new();
    public ToolboxPage() => InitializeComponent();
}
