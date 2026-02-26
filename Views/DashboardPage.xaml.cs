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
        // 若静默启动时已创建后台 VM，则复用它；否则新建
        if (App.BackgroundVm is { } bgVm)
        {
            ViewModel = bgVm;
            _started = true; // 已在 App.OnLaunched 中 Start()
        }
        else
        {
            ViewModel = new DashboardViewModel(DispatcherQueue);
        }

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
