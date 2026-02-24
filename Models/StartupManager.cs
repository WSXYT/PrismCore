using System.Diagnostics;
using Microsoft.Win32;

namespace PrismCore.Models;

/// <summary>启动项管理（对照 startup.py）。</summary>
public static class StartupManager
{
    public record StartupItem(string Name, string Command, string Source, string Location, bool Enabled);

    public static List<StartupItem> ListStartupItems()
    {
        var items = new List<StartupItem>();
        ScanRegistryRun(items);
        ScanTaskScheduler(items);
        return items;
    }

    private static void ScanRegistryRun(List<StartupItem> items)
    {
        const string disabledSuffix = @"\AutorunsDisabled";
        (RegistryKey hive, string path, string prefix)[] keys =
        [
            (Registry.CurrentUser, @"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", "HKCU"),
            (Registry.LocalMachine, @"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", "HKLM"),
        ];
        foreach (var (hive, path, prefix) in keys)
        {
            var location = $@"{prefix}\{path}";
            // 扫描已启用的启动项
            ScanRegistryKey(items, hive, path, location, enabled: true);
            // 扫描已禁用的启动项（AutorunsDisabled 子键）
            ScanRegistryKey(items, hive, path + disabledSuffix, location, enabled: false);
        }
    }

    private static void ScanRegistryKey(List<StartupItem> items, RegistryKey hive, string path, string location, bool enabled)
    {
        try
        {
            using var key = hive.OpenSubKey(path);
            if (key == null) return;
            foreach (var name in key.GetValueNames())
                items.Add(new(name, key.GetValue(name)?.ToString() ?? "", "注册表", location, enabled));
        }
        catch { }
    }

    private static void ScanTaskScheduler(List<StartupItem> items)
    {
        try
        {
            var psi = new ProcessStartInfo("schtasks", "/Query /FO CSV /NH")
            {
                CreateNoWindow = true, UseShellExecute = false,
                RedirectStandardOutput = true, RedirectStandardError = true
            };
            using var p = Process.Start(psi);
            if (p == null) return;
            var output = p.StandardOutput.ReadToEnd();
            p.WaitForExit(30000);

            foreach (var line in output.Split('\n', StringSplitOptions.RemoveEmptyEntries))
            {
                var parts = line.Trim().Trim('"').Split("\",\"");
                if (parts.Length < 3) continue;
                var name = parts[0].Trim('"');
                if (string.IsNullOrEmpty(name) || name.StartsWith(@"\Microsoft")) continue;
                var status = parts.Length > 2 ? parts[2].Trim('"') : "";
                var enabled = status is "Ready" or "就绪" or "Running" or "正在运行";
                items.Add(new(name.Split('\\')[^1], "(计划任务)", "计划任务", name, enabled));
            }
        }
        catch { }
    }

    public static bool ToggleStartupRegistry(StartupItem item, bool enable)
    {
        const string disabledSuffix = @"\AutorunsDisabled";
        try
        {
            var hive = item.Location.StartsWith("HKCU") ? Registry.CurrentUser : Registry.LocalMachine;
            var basePath = item.Location[(item.Location.IndexOf('\\') + 1)..];
            var (srcPath, dstPath) = enable
                ? (basePath + disabledSuffix, basePath)
                : (basePath, basePath + disabledSuffix);

            using var srcKey = hive.OpenSubKey(srcPath);
            if (srcKey == null) return false;
            var val = srcKey.GetValue(item.Name);
            var kind = srcKey.GetValueKind(item.Name);

            using var dstKey = hive.OpenSubKey(dstPath, true) ?? hive.CreateSubKey(dstPath);
            dstKey.SetValue(item.Name, val!, kind);

            using var delKey = hive.OpenSubKey(srcPath, true);
            delKey?.DeleteValue(item.Name);
            return true;
        }
        catch { return false; }
    }

    public static bool ToggleStartupTask(StartupItem item, bool enable)
    {
        var action = enable ? "/ENABLE" : "/DISABLE";
        try
        {
            var psi = new ProcessStartInfo("schtasks", $"/Change /TN \"{item.Location}\" {action}")
            {
                CreateNoWindow = true, UseShellExecute = false,
                RedirectStandardOutput = true, RedirectStandardError = true
            };
            using var p = Process.Start(psi);
            return p?.WaitForExit(15000) == true && p.ExitCode == 0;
        }
        catch { return false; }
    }
}
