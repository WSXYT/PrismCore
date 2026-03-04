using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using PrismCore.ViewModels;

namespace PrismCore;

public sealed partial class MainWindow : Window
{
    private DispatcherQueueTimer? _infoBarTimer;

    private readonly Dictionary<string, Type> _pageMap = new()
    {
        ["Dashboard"] = typeof(Views.DashboardPage),
        ["Cleaner"] = typeof(Views.CleanerPage),
        ["Optimizer"] = typeof(Views.OptimizerPage),
        ["Toolbox"] = typeof(Views.ToolboxPage),
        ["Update"] = typeof(Views.UpdatePage),
        ["Settings"] = typeof(Views.SettingsPage),
    };

    /// <summary>首页 ViewModel，全局共享以便生命周期管理。</summary>
    public DashboardViewModel? DashboardVm { get; set; }

    /// <summary>为 true 时关闭窗口真正退出，否则仅隐藏到托盘。</summary>
    public bool IsExiting { get; set; }

    public MainWindow()
    {
        InitializeComponent();
        Title = "PrismCore";
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);
        SetWindowIcon();
        Closed += OnClosed;
        // 默认选中首页
        NavView.SelectedItem = NavView.MenuItems[0];
    }

    /// <summary>设置窗口任务栏图标（使用 exe 嵌入的图标资源，由 csproj ApplicationIcon 编译嵌入）。</summary>
    private void SetWindowIcon()
    {
        var exePath = Environment.ProcessPath;
        if (!string.IsNullOrEmpty(exePath))
            AppWindow.SetIcon(exePath);
    }

    private void NavView_SelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (args.SelectedItem is NavigationViewItem item && item.Tag is string tag && _pageMap.TryGetValue(tag, out var pageType))
            ContentFrame.Navigate(pageType);
    }

    /// <summary>显示全局通知，3秒后自动关闭。</summary>
    public void ShowInfo(string title, string message, InfoBarSeverity severity = InfoBarSeverity.Informational)
    {
        DispatcherQueue.TryEnqueue(() =>
        {
            GlobalInfoBar.Title = title;
            GlobalInfoBar.Message = message;
            GlobalInfoBar.Severity = severity;
            GlobalInfoBar.ActionButton = null;
            GlobalInfoBar.IsOpen = true;

            if (_infoBarTimer == null)
            {
                _infoBarTimer = DispatcherQueue.CreateTimer();
                _infoBarTimer.Interval = TimeSpan.FromSeconds(3);
                _infoBarTimer.IsRepeating = false;
                _infoBarTimer.Tick += (_, _) => GlobalInfoBar.IsOpen = false;
            }
            else
            {
                _infoBarTimer.Stop();
            }
            _infoBarTimer.Start();
        });
    }

    private void OnClosed(object sender, WindowEventArgs e)
    {
        if (!IsExiting)
        {
            e.Handled = true;
            AppWindow.Hide();
            return;
        }
        DashboardVm?.Stop();
        Serilog.Log.CloseAndFlush();
    }

    /// <summary>显示全局通知（带操作按钮），不自动关闭。</summary>
    public void ShowInfoWithAction(string title, string message, string actionText, Action action,
        InfoBarSeverity severity = InfoBarSeverity.Informational)
    {
        DispatcherQueue.TryEnqueue(() =>
        {
            _infoBarTimer?.Stop();
            GlobalInfoBar.Title = title;
            GlobalInfoBar.Message = message;
            GlobalInfoBar.Severity = severity;
            var btn = new Button { Content = actionText };
            btn.Click += (_, _) =>
            {
                GlobalInfoBar.IsOpen = false;
                action();
            };
            GlobalInfoBar.ActionButton = btn;
            GlobalInfoBar.IsOpen = true;
        });
    }

    /// <summary>导航到指定页面标签。</summary>
    public void NavigateTo(string tag)
    {
        if (_pageMap.TryGetValue(tag, out var pageType))
        {
            DispatcherQueue.TryEnqueue(() =>
            {
                ContentFrame.Navigate(pageType);
                // 同步选中对应导航项（MenuItems + FooterMenuItems）
                foreach (var item in NavView.MenuItems.Concat(NavView.FooterMenuItems).OfType<NavigationViewItem>())
                {
                    if (item.Tag is string t && t == tag)
                    {
                        NavView.SelectedItem = item;
                        break;
                    }
                }
            });
        }
    }

    /// <summary>从托盘恢复窗口并激活。</summary>
    public void ShowAndActivate()
    {
        AppWindow.Show();
        Activate();
    }
}
