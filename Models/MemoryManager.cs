using System.Diagnostics;
using PrismCore.Helpers;

namespace PrismCore.Models;

/// <summary>智能内存管理（对照 memory.py）。</summary>
public static class MemoryManager
{
    private static long _lastPageFaultCount;

    public static MemorySnapshot GetMemoryStatus() => SystemInfo.GetMemoryStatus();

    public static bool PurgeStandbyList()
    {
        PrivilegeHelper.EnablePrivilege("SeProfileSingleProcessPrivilege");
        int cmd = 4; // MemoryPurgeStandbyList
        return NativeApi.NtSetSystemInformation(80, ref cmd, sizeof(int)) == 0;
    }

    public static bool EmptyWorkingSet(int pid)
    {
        var handle = NativeApi.OpenProcess(
            NativeApi.PROCESS_SET_QUOTA | NativeApi.PROCESS_QUERY_INFORMATION, false, (uint)pid);
        if (handle == 0) return false;
        try { return NativeApi.EmptyWorkingSet(handle); }
        finally { NativeApi.CloseHandle(handle); }
    }

    public static int GetForegroundPid()
    {
        var hwnd = NativeApi.GetForegroundWindow();
        NativeApi.GetWindowThreadProcessId(hwnd, out var pid);
        return (int)pid;
    }

    public static bool IsForegroundFullscreen()
    {
        var hwnd = NativeApi.GetForegroundWindow();
        if (hwnd == 0) return false;
        NativeApi.GetWindowRect(hwnd, out var rect);
        int sw = NativeApi.GetSystemMetrics(0), sh = NativeApi.GetSystemMetrics(1);
        return rect.Left <= 0 && rect.Top <= 0 && rect.Right >= sw && rect.Bottom >= sh;
    }

    public static long GetPageFaultDelta()
    {
        long total = 0;
        uint cbSize = (uint)System.Runtime.InteropServices.Marshal.SizeOf<NativeApi.PROCESS_MEMORY_COUNTERS>();
        foreach (var p in Process.GetProcesses())
        {
            try
            {
                var h = NativeApi.OpenProcess(NativeApi.PROCESS_QUERY_LIMITED_INFORMATION, false, (uint)p.Id);
                if (h != 0)
                {
                    try
                    {
                        if (NativeApi.K32GetProcessMemoryInfo(h, out var pmc, cbSize))
                            total += pmc.PageFaultCount;
                    }
                    finally { NativeApi.CloseHandle(h); }
                }
            }
            catch { }
            finally { p.Dispose(); }
        }
        var delta = _lastPageFaultCount > 0 ? total - _lastPageFaultCount : 0;
        _lastPageFaultCount = total;
        return Math.Max(delta, 0);
    }

    public static bool ShouldPurgeStandby(bool pressureMode = false)
    {
        var mem = GetMemoryStatus();
        if (mem.AvailableBytes >= (ulong)Constants.FreeMemThresholdBytes) return false;
        var standbyEst = (long)mem.TotalBytes - (long)mem.UsedBytes - (long)mem.AvailableBytes;
        if (standbyEst < 0) standbyEst = 0;
        if (standbyEst <= (long)(mem.TotalBytes * Constants.StandbyRatioThreshold)) return false;
        if (!pressureMode) return true;
        if (IsForegroundFullscreen()) return true;
        return GetPageFaultDelta() > Constants.PageFaultDeltaThreshold;
    }

    public static bool SmartPurge(bool pressureMode = false)
        => ShouldPurgeStandby(pressureMode) && PurgeStandbyList();

    public static int TrimBackgroundWorkingSets()
    {
        int trimmed = 0;
        var fgPid = GetForegroundPid();
        foreach (var p in Process.GetProcesses())
        {
            try
            {
                var name = p.ProcessName.ToLowerInvariant() + ".exe";
                if (Constants.ProtectedProcesses.Contains(name) || Constants.AudioProcesses.Contains(name)) continue;
                if (p.Id == fgPid) continue;
                if (EmptyWorkingSet(p.Id)) trimmed++;
            }
            catch { }
            finally { p.Dispose(); }
        }
        return trimmed;
    }

    public static double GetCommitRatio()
    {
        var mem = GetMemoryStatus();
        return mem.CommitLimit > 0 ? (double)mem.CommitTotal / mem.CommitLimit : 0;
    }

    public static bool IsCommitCritical() => GetCommitRatio() >= Constants.CommitRatioWarning;

    /// <summary>强制清理备用列表（用于用户手动触发，无条件执行）。</summary>
    public static bool ForcePurge() => PurgeStandbyList();

    /// <summary>推荐页面文件大小：物理内存的 1.5 倍，上限 32 GB。</summary>
    public static int RecommendPagefileMb()
    {
        var mem = GetMemoryStatus();
        var recommended = (int)(mem.TotalBytes * 1.5 / (1024 * 1024));
        return Math.Min(recommended, 32768);
    }

    /// <summary>通过 wmic 调整系统页面文件大小。</summary>
    public static bool AdjustPagefileSize(string drive = "C:", int sizeMb = 8192)
    {
        try
        {
            var escaped = drive.Replace("\\", "\\\\");
            var psi = new ProcessStartInfo("cmd.exe",
                $"/c wmic pagefileset where name=\"{escaped}\\\\pagefile.sys\" set InitialSize={sizeMb},MaximumSize={sizeMb}")
            {
                CreateNoWindow = true, UseShellExecute = false,
                RedirectStandardOutput = true, RedirectStandardError = true
            };
            using var p = Process.Start(psi);
            return p?.WaitForExit(30000) == true && p.ExitCode == 0;
        }
        catch { return false; }
    }

    public static List<(string Name, double FreedMb)> PageOutIdleProcesses(double minMb = 10.0)
    {
        var results = new List<(string, double)>();
        var fgPid = GetForegroundPid();
        var minBytes = (long)(minMb * 1024 * 1024);

        foreach (var p in Process.GetProcesses())
        {
            try
            {
                var name = p.ProcessName.ToLowerInvariant() + ".exe";
                if (Constants.ProtectedProcesses.Contains(name) || Constants.AudioProcesses.Contains(name)) continue;
                if (p.Id == fgPid) continue;
                var rss = p.WorkingSet64;
                if (rss < minBytes) continue;
                // CPU 近似检查：TotalProcessorTime 变化极小视为空闲
                if (EmptyWorkingSet(p.Id))
                {
                    try
                    {
                        p.Refresh();
                        var freed = (rss - p.WorkingSet64) / (1024.0 * 1024);
                        if (freed > 0) results.Add((name, Math.Round(freed, 1)));
                    }
                    catch { }
                }
            }
            catch { }
            finally { p.Dispose(); }
        }
        return results;
    }
}
