using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.Win32;
using Velopack;

namespace PrismCore;

/// <summary>
/// 自定义入口点，确保 Velopack 在 WinUI 启动之前处理安装/更新事件
/// </summary>
public static class Program
{
    private const string UninstallKey = @"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PrismCore";

    [STAThread]
    public static void Main(string[] args)
    {
        // Velopack 必须在最前面，处理安装、卸载、更新等钩子
        VelopackApp.Build()
            .OnAfterInstallFastCallback(v => RegisterUninstall(v.ToString()))
            .OnAfterUpdateFastCallback(v => RegisterUninstall(v.ToString()))
            .OnBeforeUninstallFastCallback(v => RemoveUninstall())
            .OnFirstRun(v => { })
            .Run();

        // 启动 WinUI 应用
        global::WinRT.ComWrappersSupport.InitializeComWrappers();
        Application.Start(p =>
        {
            var context = new DispatcherQueueSynchronizationContext(
                DispatcherQueue.GetForCurrentThread());
            SynchronizationContext.SetSynchronizationContext(context);
            _ = new App();
        });
    }

    /// <summary>在"添加或删除程序"中注册卸载入口。</summary>
    private static void RegisterUninstall(string version)
    {
        var installDir = Path.GetDirectoryName(Environment.ProcessPath)!;
        var updateExe = Path.Combine(installDir, "..", "Update.exe");
        var iconPath = Environment.ProcessPath!;

        using var key = Registry.LocalMachine.CreateSubKey(UninstallKey);
        key.SetValue("DisplayName", "PrismCore");
        key.SetValue("DisplayVersion", version);
        key.SetValue("DisplayIcon", iconPath);
        key.SetValue("Publisher", "WSXYT");
        key.SetValue("InstallLocation", installDir);
        key.SetValue("UninstallString", $"\"{Path.GetFullPath(updateExe)}\" --uninstall");
        key.SetValue("NoModify", 1, RegistryValueKind.DWord);
        key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
    }

    /// <summary>卸载时清理注册表。</summary>
    private static void RemoveUninstall()
    {
        try { Registry.LocalMachine.DeleteSubKeyTree(UninstallKey, false); }
        catch { /* 静默 */ }
    }
}
