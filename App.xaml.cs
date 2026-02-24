using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using PrismCore.Helpers;
using PrismCore.Models;
using Sentry;
using Sentry.Protocol;
using Serilog;
using System.IO;
using System.Security;
using System.Threading;
using UnhandledExceptionEventArgs = Microsoft.UI.Xaml.UnhandledExceptionEventArgs;

namespace PrismCore;

public partial class App : Application
{
    private Window? _window;
    private static Mutex? _mutex;
    private TrayIcon? _trayIcon;

    public static MainWindow? MainWindow { get; private set; }

    private static readonly string LogPath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "PrismCore", "logs", "prismcore-.log");

    public App()
    {
        InitializeComponent();
        UnhandledException += OnUnhandledException;

        try
        {
            SentrySdk.Init(options =>
            {
                options.Dsn = "https://7eca1824b7f02177b2432f1f977f742d@o4510289605296128.ingest.de.sentry.io/4510935602364496";
#if DEBUG
                options.Debug = true;
#endif
                options.AutoSessionTracking = true;
                options.IsGlobalModeEnabled = true;
                options.TracesSampleRate = 0.2;
                options.EnableLogs = true;
                options.DisableWinUiUnhandledExceptionIntegration();
            });

            Log.Logger = new LoggerConfiguration()
                .MinimumLevel.Debug()
                .WriteTo.Debug()
                .WriteTo.File(LogPath, rollingInterval: RollingInterval.Day)
                .WriteTo.Sentry()
                .CreateLogger();
        }
        catch (Exception ex)
        {
            // Sentry/Serilog 初始化失败时回退到纯文件日志
            Log.Logger = new LoggerConfiguration()
                .MinimumLevel.Debug()
                .WriteTo.Debug()
                .WriteTo.File(LogPath, rollingInterval: RollingInterval.Day)
                .CreateLogger();
            Log.Error(ex, "Sentry 初始化失败");
        }
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        _mutex = new Mutex(true, "PrismCore_SingleInstance", out var isNew);
        if (!isNew)
        {
            Environment.Exit(0);
            return;
        }

        _window = new MainWindow();
        MainWindow = (MainWindow)_window;
        _window.Activate();

        // 创建系统托盘图标
        _trayIcon = new TrayIcon();
        _trayIcon.ShowRequested += () => MainWindow.DispatcherQueue.TryEnqueue(() => MainWindow.ShowAndActivate());
        _trayIcon.OptimizeRequested += () => MainWindow.DispatcherQueue.TryEnqueue(() => MainWindow.DashboardVm?.SmartOptimizeCommand.Execute(null));
        _trayIcon.ExitRequested += () => MainWindow.DispatcherQueue.TryEnqueue(() =>
        {
            MainWindow.IsExiting = true;
            _trayIcon?.Dispose();
            MainWindow.Close();
        });
        _trayIcon.Create();

        Log.Information("PrismCore 已启动");

        // 启动时自动更新检查
        var updateMode = AppSettings.Instance.UpdateMode;
        if (updateMode > 0)
            _ = CheckUpdateOnStartupAsync(updateMode);
    }

    private static async Task CheckUpdateOnStartupAsync(int mode)
    {
        try
        {
            var svc = new UpdateService();
            var update = await svc.CheckForUpdateAsync();
            if (update == null) return;

            var version = update.TargetFullRelease.Version.ToString();

            if (mode == 1)
            {
                // 仅通知
                MainWindow?.ShowInfoWithAction(
                    "发现新版本",
                    $"新版本 {version} 可用",
                    "前往更新",
                    () => MainWindow?.NavigateTo("Update"),
                    InfoBarSeverity.Informational);
            }
            else if (mode == 2)
            {
                // 自动下载并安装
                Log.Information("自动更新模式：开始下载 {Version}", version);
                await svc.DownloadAndApplyAsync(update);
            }
        }
        catch (Exception ex)
        {
            Log.Error(ex, "启动时自动更新检查失败");
        }
    }

    [SecurityCritical]
    private void OnUnhandledException(object sender, UnhandledExceptionEventArgs e)
    {
        var exception = e.Exception;
        if (exception != null)
        {
            exception.Data[Mechanism.HandledKey] = false;
            exception.Data[Mechanism.MechanismKey] = "Application.UnhandledException";
            SentrySdk.CaptureException(exception);
            Log.Fatal(exception, "未处理的异常");
            SentrySdk.FlushAsync(TimeSpan.FromSeconds(2)).GetAwaiter().GetResult();
        }
        e.Handled = true;
    }
}
