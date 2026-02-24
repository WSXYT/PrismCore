using System.Diagnostics;
using PrismCore.Helpers;

namespace PrismCore.Models;

/// <summary>后台自动优化器（对照 auto_optimizer.py）。</summary>
public static class AutoOptimizer
{
    private static readonly Dictionary<string, string> _createdPagefiles = [];
    private static int _currentPagefileSizeMb;

    public static void RestorePagefileState()
    {
        var info = AppSettings.Instance.PagefileInfo;
        if (info == null) return;
        var drive = info.TryGetValue("drive", out var d) ? d?.ToString() ?? "" : "";
        var path = Path.Combine(drive, "pagefile.sys");
        if (!File.Exists(path)) { AppSettings.Instance.PagefileInfo = null; return; }
        var method = info.TryGetValue("method", out var m) ? m?.ToString() ?? "" : "";
        _createdPagefiles[drive] = method;
        _currentPagefileSizeMb = info.TryGetValue("size_mb", out var s)
            && int.TryParse(s?.ToString(), out var sz) ? sz : 0;
    }

    public static int CalcHealthScore(double cpuPct = 0)
    {
        var mem = SystemInfo.GetMemoryStatus();

        static int Score(double pct, int full, double low, double high)
            => pct <= low ? full : pct >= high ? 0 : (int)(full * (high - pct) / (high - low));

        int memScore = Score(mem.UsagePercent, 40, 70, 95);
        int cpuScore = Score(cpuPct, 30, 50, 95);

        int diskScore = 30;
        foreach (var drive in DriveInfo.GetDrives())
        {
            try
            {
                if (!drive.IsReady) continue;
                var pct = (double)(drive.TotalSize - drive.AvailableFreeSpace) / drive.TotalSize * 100;
                diskScore = Math.Min(diskScore, Score(pct, 30, 70, 95));
            }
            catch { }
        }
        return Math.Min(100, memScore + cpuScore + diskScore);
    }

    public static List<string> CheckAndAutoOptimize()
    {
        var actions = new List<string>();
        var mem = SystemInfo.GetMemoryStatus();

        if (mem.AvailableBytes < (ulong)Constants.FreeMemThresholdBytes)
        {
            if (MemoryManager.SmartPurge(pressureMode: true))
                actions.Add("已自动清理内存备用列表");
            int count = MemoryManager.TrimBackgroundWorkingSets();
            if (count > 0) actions.Add($"已自动修剪 {count} 个后台进程");
        }

        if (mem.CommitLimit > 0)
        {
            var ratio = (double)mem.CommitTotal / mem.CommitLimit;
            if (ratio >= Constants.CommitRatioWarning)
            {
                var result = CreateTempPagefileDynamic();
                result ??= CreateTempPagefile();
                if (result != null) actions.Add(result);
            }
        }
        return actions;
    }

    public static string? FindBestDrive()
    {
        string? best = null; long bestFree = 0;
        string? cDrive = null;
        long minFree = 8L * 1024 * 1024 * 1024;

        foreach (var d in DriveInfo.GetDrives())
        {
            try
            {
                if (!d.IsReady || d.DriveType != DriveType.Fixed) continue;
                var free = d.AvailableFreeSpace;
                if (d.Name.StartsWith("C", StringComparison.OrdinalIgnoreCase))
                { if (free > minFree) cDrive = d.Name; continue; }
                if (free > minFree && free > bestFree) { bestFree = free; best = d.Name; }
            }
            catch { }
        }
        return best ?? cDrive;
    }

    public static string? CreateTempPagefileDynamic(int sizeMb = 4096)
    {
        var drive = FindBestDrive();
        if (drive == null) return null;
        var letter = drive.TrimEnd('\\').TrimEnd(':');
        var ntPath = $@"\??\{letter}:\pagefile.sys";
        var sizeBytes = (long)sizeMb * 1024 * 1024;

        PrivilegeHelper.EnablePrivilege("SeCreatePagefilePrivilege");
        if (NtCreatePagingFile(ntPath, sizeBytes))
        {
            _createdPagefiles[drive] = "dynamic";
            _currentPagefileSizeMb = sizeMb;
            SavePagefileInfo(drive, "dynamic", sizeMb);
            return $"已在 {drive} 动态扩展 {sizeMb}MB 分页文件";
        }
        return null;
    }

    public static string? CreateTempPagefile(int sizeMb = 4096)
    {
        var drive = FindBestDrive();
        if (drive == null) return null;
        var letter = drive.TrimEnd('\\');
        try
        {
            RunCmd($"wmic pagefileset create name=\"{letter}\\pagefile.sys\"");
            RunCmd($"wmic pagefileset where name=\"{letter.Replace("\\", "\\\\")}\\\\pagefile.sys\" set InitialSize={sizeMb},MaximumSize={sizeMb}");
            _createdPagefiles[drive] = "wmic";
            SavePagefileInfo(drive, "wmic", sizeMb);
            return $"已在 {drive} 创建 {sizeMb}MB 临时分页文件（需重启生效）";
        }
        catch { return null; }
    }

    public static List<string> RemoveAllTempPagefiles()
    {
        var removed = new List<string>();
        foreach (var (drive, method) in _createdPagefiles.ToList())
        {
            if (method == "dynamic") removed.Add(drive);
            else if (RemoveTempPagefile(drive)) removed.Add(drive);
        }
        foreach (var d in removed) _createdPagefiles.Remove(d);
        _currentPagefileSizeMb = 0;
        AppSettings.Instance.PagefileInfo = null;
        return removed;
    }

    public static string? ExpandPagefileIncremental(int thresholdPct = 80)
    {
        if (_currentPagefileSizeMb >= 8192) return null;
        var mem = SystemInfo.GetMemoryStatus();
        if (mem.CommitLimit == 0) return null;
        var ratio = (double)mem.CommitTotal / mem.CommitLimit;
        if (ratio * 100 <= thresholdPct) return null;

        var thresholdBytes = (long)((double)mem.CommitLimit * thresholdPct / 100.0);
        var needBytes = (long)mem.CommitTotal - thresholdBytes;
        var expandMb = Math.Max(256, (int)(needBytes * 1.2 / (1024 * 1024)));
        var newTotal = Math.Min(_currentPagefileSizeMb + expandMb, 8192);
        if (newTotal <= _currentPagefileSizeMb) return null;

        var drive = FindBestDrive();
        if (drive == null) return null;
        var letter = drive.TrimEnd('\\').TrimEnd(':');
        var ntPath = $@"\??\{letter}:\pagefile.sys";

        PrivilegeHelper.EnablePrivilege("SeCreatePagefilePrivilege");
        if (NtCreatePagingFile(ntPath, (long)newTotal * 1024 * 1024))
        {
            _currentPagefileSizeMb = newTotal;
            _createdPagefiles[drive] = "dynamic";
            SavePagefileInfo(drive, "dynamic", newTotal);
            return $"已在 {drive} 扩展分页文件至 {newTotal}MB";
        }
        return CreateTempPagefile(newTotal);
    }

    public static List<string> GetCreatedPagefiles() => [.. _createdPagefiles.Keys];
    public static int CurrentPagefileSizeMb => _currentPagefileSizeMb;

    private static bool RemoveTempPagefile(string drive)
    {
        try
        {
            var letter = drive.TrimEnd('\\');
            RunCmd($"wmic pagefileset where name=\"{letter.Replace("\\", "\\\\")}\\\\pagefile.sys\" delete");
            return true;
        }
        catch { return false; }
    }

    private static void SavePagefileInfo(string drive, string method, int sizeMb)
    {
        // 统一存储为字符串，避免 object 装箱后与 JsonElement 反序列化类型不一致
        AppSettings.Instance.PagefileInfo = new()
        {
            ["drive"] = drive, ["method"] = method,
            ["size_mb"] = sizeMb.ToString(), ["created_at"] = DateTime.Now.ToString("o")
        };
    }

    private static bool NtCreatePagingFile(string ntPath, long sizeBytes)
    {
        unsafe
        {
            fixed (char* pathPtr = ntPath)
            {
                var us = new NativeApi.UNICODE_STRING
                {
                    Length = (ushort)(ntPath.Length * 2),
                    MaximumLength = (ushort)(ntPath.Length * 2 + 2),
                    Buffer = (nint)pathPtr
                };
                var min = new NativeApi.LARGE_INTEGER { QuadPart = sizeBytes };
                var max = new NativeApi.LARGE_INTEGER { QuadPart = sizeBytes };
                return NativeApi.NtCreatePagingFile(ref us, ref min, ref max, 0) == 0;
            }
        }
    }

    private static void RunCmd(string cmd)
        => Helpers.ProcessHelper.RunCmd(cmd);
}
