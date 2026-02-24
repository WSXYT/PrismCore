using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using PrismCore.Models;

namespace PrismCore.Views;

public sealed partial class SettingsPage : Page
{
    private readonly AppSettings _s = AppSettings.Instance;

    public SettingsPage() => InitializeComponent();

    private void NotifyDashboard()
    {
        if (App.MainWindow is { DashboardVm: { } vm }) vm.ReloadSettings();
    }

    // 后台自动优化
    public bool AutoOptimizeEnabled { get => _s.AutoOptimizeEnabled; set { _s.AutoOptimizeEnabled = value; NotifyDashboard(); } }
    public double MemoryThreshold { get => _s.MemoryThreshold; set { _s.MemoryThreshold = (int)value; NotifyDashboard(); } }
    public double AutoOptimizeInterval { get => _s.AutoOptimizeInterval; set { _s.AutoOptimizeInterval = (int)value; NotifyDashboard(); } }

    // 虚拟内存
    public bool AutoPagefileEnabled { get => _s.AutoPagefileEnabled; set { _s.AutoPagefileEnabled = value; NotifyDashboard(); } }
    public double PagefileExpandThreshold { get => _s.PagefileExpandThreshold; set { _s.PagefileExpandThreshold = (int)value; NotifyDashboard(); } }
    public bool PagefileSuggestionEnabled { get => _s.PagefileSuggestionEnabled; set => _s.PagefileSuggestionEnabled = value; }

    // 智能调度
    public bool ProBalanceEnabled { get => _s.ProBalanceEnabled; set { _s.ProBalanceEnabled = value; NotifyDashboard(); } }
    public double ProBalanceSystemThreshold { get => _s.ProBalanceSystemThreshold; set { _s.ProBalanceSystemThreshold = (int)value; NotifyDashboard(); } }
    public double ProBalanceProcessThreshold { get => _s.ProBalanceProcessThreshold; set { _s.ProBalanceProcessThreshold = (int)value; NotifyDashboard(); } }

    // 异常检测
    public bool AnomalyEnabled { get => _s.AnomalyEnabled; set => _s.AnomalyEnabled = value; }
    public double AnomalyZThreshold { get => _s.AnomalyZThreshold; set => _s.AnomalyZThreshold = value; }
    public double AnomalyEwmaAlpha { get => _s.AnomalyEwmaAlpha; set => _s.AnomalyEwmaAlpha = value; }

    // 内存优化策略
    public bool PurgeStandbyEnabled { get => _s.PurgeStandbyEnabled; set => _s.PurgeStandbyEnabled = value; }
    public bool TrimWorkingSetsEnabled { get => _s.TrimWorkingSetsEnabled; set => _s.TrimWorkingSetsEnabled = value; }
    public bool PageOutIdleEnabled { get => _s.PageOutIdleEnabled; set => _s.PageOutIdleEnabled = value; }

    // 系统监控
    public bool DpcMonitorEnabled { get => _s.DpcMonitorEnabled; set { _s.DpcMonitorEnabled = value; NotifyDashboard(); } }

    private async void ResetDefaults_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new ContentDialog
        {
            Title = "恢复默认设置",
            Content = "确定要将所有设置恢复为默认值吗？",
            PrimaryButtonText = "确定",
            CloseButtonText = "取消",
            DefaultButton = ContentDialogButton.Close,
            XamlRoot = XamlRoot
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary) return;
        _s.ResetToDefaults();
        // 刷新页面以显示默认值
        Frame.Navigate(typeof(SettingsPage));
        // 通知 Dashboard 重新加载设置
        if (App.MainWindow is { DashboardVm: { } vm }) vm.ReloadSettings();
    }
}
