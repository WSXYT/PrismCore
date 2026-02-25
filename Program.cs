using System.ComponentModel;
using System.Diagnostics;
using System.Security.Principal;
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
        // 钩子以普通权限运行（asInvoker），不会触发"请求需要提升"
        VelopackApp.Build()
            .OnAfterInstallFastCallback(v => RegisterUninstall(v.ToString()))
            .OnAfterUpdateFastCallback(v => RegisterUninstall(v.ToString()))
            .OnBeforeUninstallFastCallback(v => RemoveUninstall())
            .OnFirstRun(v => { })
            .Run();

        // 正常启动时，若未提权则自提权后退出当前进程
        if (!IsElevated())
        {
            try
            {
                Process.Start(new ProcessStartInfo
                {
                    FileName = Environment.ProcessPath!,
                    Arguments = string.Join(' ', args),
                    UseShellExecute = true,
                    Verb = "runas"
                });
            }
            catch (Win32Exception)
            {
                // 用户拒绝了 UAC，静默退出
            }
            return;
        }

        // 以管理员身份启动 WinUI 应用
        global::WinRT.ComWrappersSupport.InitializeComWrappers();
        Application.Start(p =>
        {
            var context = new DispatcherQueueSynchronizationContext(
                DispatcherQueue.GetForCurrentThread());
            SynchronizationContext.SetSynchronizationContext(context);
            _ = new App();
        });
    }

    private static bool IsElevated()
    {
        using var identity = WindowsIdentity.GetCurrent();
        var principal = new WindowsPrincipal(identity);
        return principal.IsInRole(WindowsBuiltInRole.Administrator);
    }

    /// <summary>在"添加或删除程序"中注册卸载入口（HKCU，无需提权）。</summary>
    private static void RegisterUninstall(string version)
    {
        var installDir = Path.GetDirectoryName(Environment.ProcessPath)!;
        var updateExe = Path.Combine(installDir, "..", "Update.exe");
        var iconPath = Environment.ProcessPath!;

        using var key = Registry.CurrentUser.CreateSubKey(UninstallKey);
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
        try { Registry.CurrentUser.DeleteSubKeyTree(UninstallKey, false); } catch { }
    }
}
