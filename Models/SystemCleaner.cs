using System.Diagnostics;
using Microsoft.Win32;
using PrismCore.Helpers;

namespace PrismCore.Models;

/// <summary>系统级清理操作（对照 system_cleaner.py）。</summary>
public static class SystemCleaner
{
    public record SystemCleanResult(string Action, bool Success, string Message, long FreedBytes = 0);

    // ── WinSxS 组件存储 ──

    public static SystemCleanResult CleanupWinsxs(bool aggressive = false)
    {
        var args = "/Online /Cleanup-Image /StartComponentCleanup";
        if (aggressive) args += " /ResetBase";
        return RunDism(args, "WinSxS");
    }

    private static SystemCleanResult RunDism(string args, string action)
    {
        try
        {
            var psi = new ProcessStartInfo("Dism.exe", args)
            {
                CreateNoWindow = true, UseShellExecute = false,
                RedirectStandardOutput = true, RedirectStandardError = true
            };
            using var p = Process.Start(psi);
            p?.WaitForExit(600000);
            return new(action, p?.ExitCode == 0, "组件存储清理完成");
        }
        catch (Exception e) { return new(action, false, $"清理失败: {e.Message}"); }
    }

    // ── 驱动商店 ──

    public static List<Dictionary<string, string>> ListOldDrivers()
    {
        try
        {
            var psi = new ProcessStartInfo("pnputil", "/enum-drivers")
            {
                CreateNoWindow = true, UseShellExecute = false,
                RedirectStandardOutput = true, RedirectStandardError = true
            };
            using var p = Process.Start(psi);
            if (p == null) return [];
            var output = p.StandardOutput.ReadToEnd();
            p.WaitForExit(60000);

            var drivers = new List<Dictionary<string, string>>();
            foreach (var block in output.Split("\n\n", StringSplitOptions.RemoveEmptyEntries))
            {
                var fields = block.Trim().Split('\n')
                    .Where(l => l.Contains(':'))
                    .Select(l => l[(l.IndexOf(':') + 1)..].Trim())
                    .ToList();
                if (fields.Count < 4) continue;
                var d = new Dictionary<string, string> { ["inf"] = fields[0] };
                if (fields.Count > 3) d["class"] = fields[3];
                if (fields.Count > 5) d["version"] = fields[5];
                if (!string.IsNullOrEmpty(d["inf"])) drivers.Add(d);
            }

            // 按类分组，保留最新，标记旧版本
            var removable = new List<Dictionary<string, string>>();
            foreach (var group in drivers.GroupBy(d => d.GetValueOrDefault("class", "")))
            {
                var items = group.ToList();
                if (items.Count > 1) removable.AddRange(items[..^1]);
            }
            return removable;
        }
        catch { return []; }
    }

    public static bool DeleteDriver(string infName)
    {
        try
        {
            var psi = new ProcessStartInfo("pnputil", $"/delete-driver {infName}")
            {
                CreateNoWindow = true, UseShellExecute = false,
                RedirectStandardOutput = true, RedirectStandardError = true
            };
            using var p = Process.Start(psi);
            return p?.WaitForExit(30000) == true && p.ExitCode == 0;
        }
        catch { return false; }
    }

    // ── CompactOS ──

    public static bool ShouldCompactOs()
    {
        try
        {
            var di = new DriveInfo("C");
            return di.AvailableFreeSpace < Constants.DiskCriticalBytes;
        }
        catch { return false; }
    }

    public static SystemCleanResult EnableCompactOs()
    {
        try
        {
            var psi = new ProcessStartInfo("compact.exe", "/CompactOS:always")
            {
                CreateNoWindow = true, UseShellExecute = false,
                RedirectStandardOutput = true, RedirectStandardError = true
            };
            using var p = Process.Start(psi);
            p?.WaitForExit(600000);
            return new("CompactOS", p?.ExitCode == 0, "系统文件已压缩");
        }
        catch (Exception e) { return new("CompactOS", false, $"压缩失败: {e.Message}"); }
    }

    public static bool QueryCompactOsStatus()
    {
        try
        {
            var psi = new ProcessStartInfo("compact.exe", "/CompactOS:query")
            {
                CreateNoWindow = true, UseShellExecute = false,
                RedirectStandardOutput = true, RedirectStandardError = true
            };
            using var p = Process.Start(psi);
            if (p == null) return false;
            var output = p.StandardOutput.ReadToEnd();
            p.WaitForExit(30000);
            return output.Contains("未") || output.Contains("not", StringComparison.OrdinalIgnoreCase);
        }
        catch { return false; }
    }

    // ── 注册表孤立项 ──

    public static List<Dictionary<string, string>> ScanOrphanRegistry()
    {
        var orphans = new List<Dictionary<string, string>>();
        ScanClsidOrphans(orphans);
        ScanAppPathsOrphans(orphans);
        ScanUninstallOrphans(orphans);
        return orphans;
    }

    private static void ScanClsidOrphans(List<Dictionary<string, string>> orphans)
    {
        try
        {
            using var key = Registry.ClassesRoot.OpenSubKey("CLSID");
            if (key == null) return;
            foreach (var name in key.GetSubKeyNames())
            {
                try
                {
                    using var srv = key.OpenSubKey($@"{name}\InProcServer32");
                    var dll = srv?.GetValue("")?.ToString();
                    if (dll != null && !File.Exists(Environment.ExpandEnvironmentVariables(dll)))
                        orphans.Add(new() {
                            ["key"] = $@"HKCR\CLSID\{name}", ["type"] = "CLSID", ["ref"] = dll
                        });
                }
                catch { }
            }
        }
        catch { }
    }

    private static void ScanAppPathsOrphans(List<Dictionary<string, string>> orphans)
    {
        const string path = @"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths";
        try
        {
            using var key = Registry.LocalMachine.OpenSubKey(path);
            if (key == null) return;
            foreach (var name in key.GetSubKeyNames())
            {
                try
                {
                    using var sub = key.OpenSubKey(name);
                    var exe = sub?.GetValue("")?.ToString();
                    if (exe != null && !File.Exists(Environment.ExpandEnvironmentVariables(exe)))
                        orphans.Add(new() {
                            ["key"] = $@"HKLM\{path}\{name}", ["type"] = "AppPath", ["ref"] = exe
                        });
                }
                catch { }
            }
        }
        catch { }
    }

    private static void ScanUninstallOrphans(List<Dictionary<string, string>> orphans)
    {
        const string path = @"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall";
        try
        {
            using var key = Registry.LocalMachine.OpenSubKey(path);
            if (key == null) return;
            foreach (var name in key.GetSubKeyNames())
            {
                try
                {
                    using var sub = key.OpenSubKey(name);
                    var loc = sub?.GetValue("InstallLocation")?.ToString();
                    if (!string.IsNullOrWhiteSpace(loc) &&
                        !Directory.Exists(Environment.ExpandEnvironmentVariables(loc)))
                        orphans.Add(new() {
                            ["key"] = $@"HKLM\{path}\{name}", ["type"] = "Uninstall", ["ref"] = loc
                        });
                }
                catch { }
            }
        }
        catch { }
    }

    public static bool BackupAndDeleteKey(string keyPath)
    {
        Directory.CreateDirectory(Constants.RegistryBackupDir);
        var safeName = keyPath.Replace('\\', '_').Replace('/', '_');
        var backupFile = Path.Combine(Constants.RegistryBackupDir, $"{safeName}.reg");
        try
        {
            RunCmd("reg", $"export \"{keyPath}\" \"{backupFile}\" /y");
            RunCmd("reg", $"delete \"{keyPath}\" /f");
            return true;
        }
        catch { return false; }
    }

    // ── Windows Update 缓存 ──

    public static SystemCleanResult CleanupWindowsUpdate()
    {
        var dlPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.Windows),
            "SoftwareDistribution", "Download");
        if (!Directory.Exists(dlPath))
            return new("WinUpdate", false, "目录不存在");

        long freed = 0;
        foreach (var entry in new DirectoryInfo(dlPath).EnumerateFileSystemInfos())
        {
            try
            {
                if (entry is DirectoryInfo di)
                {
                    freed += DirSize(di.FullName);
                    di.Delete(true);
                }
                else if (entry is FileInfo fi)
                {
                    freed += fi.Length;
                    fi.Delete();
                }
            }
            catch { }
        }
        return new("WinUpdate", true, "已清理更新缓存", freed);
    }

    public static long ScanUpdateCacheSize()
    {
        var dlPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.Windows),
            "SoftwareDistribution", "Download");
        return Directory.Exists(dlPath) ? DirSize(dlPath) : 0;
    }

    // ── 系统还原点 ──

    public static bool CreateRestorePoint(string description = "PrismCore 自动还原点")
    {
        var info = new NativeApi.RESTOREPTINFOW
        {
            dwEventType = NativeApi.BEGIN_SYSTEM_CHANGE,
            dwRestorePtType = NativeApi.APPLICATION_INSTALL,
            szDescription = description
        };
        return NativeApi.SRSetRestorePointW(ref info, out _);
    }

    private static long DirSize(string path)
    {
        long total = 0;
        var stack = new Stack<string>();
        stack.Push(path);
        while (stack.Count > 0)
        {
            var dir = stack.Pop();
            try
            {
                foreach (var f in Directory.GetFiles(dir))
                    try { total += new FileInfo(f).Length; } catch { }
                foreach (var d in Directory.GetDirectories(dir))
                    stack.Push(d);
            }
            catch { }
        }
        return total;
    }

    // ── 扫描估算函数（用于整合到统一扫描流程）──

    /// <summary>扫描旧驱动，返回可删除列表。复用 ListOldDrivers。</summary>
    public static List<Dictionary<string, string>> ScanOldDriversInfo() => ListOldDrivers();

    /// <summary>扫描孤立注册表项。复用 ScanOrphanRegistry。</summary>
    public static List<Dictionary<string, string>> ScanOrphanRegistryInfo() => ScanOrphanRegistry();

    private static void RunCmd(string exe, string args)
    {
        var psi = new ProcessStartInfo(exe, args)
        {
            CreateNoWindow = true, UseShellExecute = false,
            RedirectStandardOutput = true, RedirectStandardError = true
        };
        using var p = Process.Start(psi);
        p?.WaitForExit(15000);
    }
}
