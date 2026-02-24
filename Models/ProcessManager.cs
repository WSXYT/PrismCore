using System.Diagnostics;
using PrismCore.Helpers;

namespace PrismCore.Models;

/// <summary>进程管理（对照 process_manager.py）。</summary>
public static class ProcessManager
{
    public record ProcessInfo(int Pid, string Name, double MemoryMb, string Status);

    public static List<ProcessInfo> ListTopProcesses(int count = 30)
    {
        var list = new List<ProcessInfo>();
        foreach (var p in Process.GetProcesses())
        {
            try
            {
                list.Add(new(p.Id, p.ProcessName,
                    Math.Round(p.WorkingSet64 / (1024.0 * 1024), 1),
                    p.Responding ? "运行中" : "无响应"));
            }
            catch { }
            finally { p.Dispose(); }
        }
        list.Sort((a, b) => b.MemoryMb.CompareTo(a.MemoryMb));
        return list.Count > count ? list[..count] : list;
    }

    public static bool SetProcessPriority(int pid, ProcessPriorityClass priority)
    {
        try
        {
            using var p = Process.GetProcessById(pid);
            if (Constants.ProtectedProcesses.Contains(p.ProcessName.ToLowerInvariant() + ".exe"))
                return false;
            p.PriorityClass = priority;
            return true;
        }
        catch { return false; }
    }

    public static bool SetProcessAffinity(int pid, nint mask)
    {
        try
        {
            using var p = Process.GetProcessById(pid);
            if (Constants.ProtectedProcesses.Contains(p.ProcessName.ToLowerInvariant() + ".exe"))
                return false;
            p.ProcessorAffinity = mask;
            return true;
        }
        catch { return false; }
    }

    public static bool BoostForeground(int pid)
    {
        int logical = Environment.ProcessorCount;
        int physical = Math.Max(logical / 2, 1);
        long mask = 0;
        for (int i = 0; i < physical; i++) mask |= 1L << i;
        bool ok1 = SetProcessPriority(pid, ProcessPriorityClass.High);
        bool ok2 = SetProcessAffinity(pid, (nint)mask);
        return ok1 || ok2;
    }

    public static bool ThrottleBackground(int pid)
    {
        int logical = Environment.ProcessorCount;
        int physical = Math.Max(logical / 2, 1);
        if (logical <= physical)
            return SetProcessPriority(pid, ProcessPriorityClass.Idle);
        long mask = 0;
        for (int i = physical; i < logical; i++) mask |= 1L << i;
        bool ok1 = SetProcessPriority(pid, ProcessPriorityClass.Idle);
        bool ok2 = SetProcessAffinity(pid, (nint)mask);
        return ok1 || ok2;
    }
}
