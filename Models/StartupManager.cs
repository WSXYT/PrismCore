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
            var r = Helpers.ProcessHelper.Run("schtasks", "/Query /FO CSV /NH");
            var output = r.Output;

            foreach (var line in output.Split('\n', StringSplitOptions.RemoveEmptyEntries))
            {
                var trimmed = line.Trim();
                if (trimmed.Length < 2 || trimmed[0] != '"') continue;
                // 解析 CSV：按 "," 分割（字段被双引号包裹）
                var parts = trimmed[1..^1].Split("\",\"");
                if (parts.Length < 3) continue;
                var name = parts[0];
                if (string.IsNullOrEmpty(name) || name.StartsWith(@"\Microsoft")) continue;
                var status = parts.Length > 2 ? parts[2] : "";
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
        try { return Helpers.ProcessHelper.Run("schtasks", $"/Change /TN \"{item.Location}\" {action}", 15000).Success; }
        catch { return false; }
    }
}
