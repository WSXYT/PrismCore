using Microsoft.UI.Xaml.Controls;
using PrismCore.ViewModels;

namespace PrismCore.Views;

public sealed partial class UpdatePage : Page
{
    public UpdateViewModel ViewModel { get; } = new();
    public UpdatePage() => InitializeComponent();
}
