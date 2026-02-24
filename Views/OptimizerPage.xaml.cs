using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using PrismCore.Models;
using PrismCore.ViewModels;

namespace PrismCore.Views;

public sealed partial class OptimizerPage : Page
{
    public OptimizerViewModel ViewModel { get; } = new();

    public OptimizerPage()
    {
        InitializeComponent();
        Loaded += async (_, _) => await ViewModel.LoadAsync();
    }

    private void OnStartupToggled(object sender, RoutedEventArgs e)
    {
        if (sender is ToggleSwitch ts && ts.DataContext is StartupManager.StartupItem item
            && ts.IsOn != item.Enabled)
        {
            var msg = ViewModel.ToggleStartup(item, ts.IsOn);
            if (App.MainWindow is { } mw)
                mw.ShowInfo("启动项", msg, ts.IsOn
                    ? Microsoft.UI.Xaml.Controls.InfoBarSeverity.Success
                    : Microsoft.UI.Xaml.Controls.InfoBarSeverity.Informational);
        }
    }

    private void OnBoost(object sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.Tag is int pid)
            ViewModel.BoostProcess(pid);
    }

    private void OnThrottle(object sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.Tag is int pid)
            ViewModel.ThrottleProcess(pid);
    }
}
