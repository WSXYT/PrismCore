namespace PrismCore.Models;

/// <summary>系统信息快照结构（对照 system_info.py）。</summary>
public record CpuSnapshot(double UsagePercent, double PredictedPercent);

public record DiskSnapshot(string Drive, ulong TotalBytes, ulong FreeBytes)
{
    public double UsagePercent => TotalBytes > 0 ? (double)(TotalBytes - FreeBytes) / TotalBytes * 100 : 0;
}

public record MemorySnapshot(
    ulong TotalBytes, ulong AvailableBytes, ulong UsedBytes, double UsagePercent,
    ulong CommitTotal, ulong CommitLimit)
{
    public double CommitRatio => CommitLimit > 0 ? (double)CommitTotal / CommitLimit : 0;
}

public static class SystemInfo
{
    public static MemorySnapshot GetMemoryStatus()
    {
        var ms = new Helpers.NativeApi.MEMORYSTATUSEX { dwLength = 64 };
        Helpers.NativeApi.GlobalMemoryStatusEx(ref ms);
        var used = ms.ullTotalPhys - ms.ullAvailPhys;
        var pct = ms.ullTotalPhys > 0 ? (double)used / ms.ullTotalPhys * 100 : 0;
        return new MemorySnapshot(
            ms.ullTotalPhys, ms.ullAvailPhys, used, Math.Round(pct, 1),
            ms.ullTotalPageFile - ms.ullAvailPageFile, ms.ullTotalPageFile);
    }

    public static ulong GetDiskFree(string drive = @"C:\")
    {
        Helpers.NativeApi.GetDiskFreeSpaceExW(drive, out var free, out _, out _);
        return free;
    }

    public static List<DiskSnapshot> GetDiskSnapshots()
    {
        var list = new List<DiskSnapshot>();
        foreach (var d in DriveInfo.GetDrives())
        {
            try
            {
                if (!d.IsReady) continue;
                list.Add(new DiskSnapshot(d.Name, (ulong)d.TotalSize, (ulong)d.AvailableFreeSpace));
            }
            catch { }
        }
        return list;
    }

    /// <summary>通过 SendMessageTimeoutW 测量系统 UI 响应延迟（毫秒）。</summary>
    public static double MeasureResponsiveness(uint timeoutMs = 5000)
    {
        var sw = System.Diagnostics.Stopwatch.StartNew();
        var ret = Helpers.NativeApi.SendMessageTimeoutW(
            (nint)0xFFFF, Helpers.NativeApi.WM_NULL, 0, 0,
            0x0002 /*SMTO_ABORTIFHUNG*/, timeoutMs, out _);
        sw.Stop();
        return ret == 0 ? timeoutMs : Math.Round(sw.Elapsed.TotalMilliseconds, 2);
    }

    public static string FormatBytes(ulong bytes)
    {
        string[] units = ["B", "KB", "MB", "GB", "TB"];
        double size = bytes;
        int i = 0;
        while (size >= 1024 && i < units.Length - 1) { size /= 1024; i++; }
        return $"{size:F1} {units[i]}";
    }
}
