using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml.Controls;
using PrismCore.ViewModels;

namespace PrismCore.Views;

public sealed partial class DashboardPage : Page
{
    public DashboardViewModel ViewModel { get; }
    private bool _started;

    public DashboardPage()
    {
        ViewModel = new DashboardViewModel(DispatcherQueue);
        InitializeComponent();

        // 注册到 MainWindow 以便关闭时清理
        if (App.MainWindow is { } mw)
        {
            mw.DashboardVm = ViewModel;
            ViewModel.AutoAction += msg =>
                mw.ShowInfo("自动优化", msg, Microsoft.UI.Xaml.Controls.InfoBarSeverity.Informational);
        }

        Loaded += (_, _) =>
        {
            if (!_started) { ViewModel.Start(); _started = true; }
        };
    }
}
