using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using PrismCore.ViewModels;

namespace PrismCore.Views;

public sealed partial class CleanerPage : Page
{
    public CleanerViewModel ViewModel { get; } = new();
    public CleanerPage() => InitializeComponent();

    private void OnQuickScan(object sender, RoutedEventArgs e) => ViewModel.ScanCommand.Execute(false);
    private void OnDeepScan(object sender, RoutedEventArgs e) => ViewModel.ScanCommand.Execute(true);
}
