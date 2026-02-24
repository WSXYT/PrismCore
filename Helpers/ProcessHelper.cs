using System.Diagnostics;

namespace PrismCore.Helpers;

/// <summary>安全的进程执行工具，避免重定向流死锁。</summary>
public static class ProcessHelper
{
    public record RunResult(int ExitCode, string Output, string Error)
    {
        public bool Success => ExitCode == 0;
    }

    /// <summary>执行外部进程，并发读取 stdout/stderr 避免管道死锁。</summary>
    public static RunResult Run(string exe, string args, int timeoutMs = 30000)
    {
        using var p = new Process();
        p.StartInfo = new ProcessStartInfo(exe, args)
        {
            CreateNoWindow = true,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        p.Start();
        // 并发读取两个流，任一管道缓冲区满都不会阻塞子进程
        var stdoutTask = p.StandardOutput.ReadToEndAsync();
        var stderrTask = p.StandardError.ReadToEndAsync();
        if (!p.WaitForExit(timeoutMs))
        {
            try { p.Kill(true); } catch { }
            return new(-1, stdoutTask.Result, stderrTask.Result);
        }
        return new(p.ExitCode, stdoutTask.Result, stderrTask.Result);
    }

    /// <summary>通过 cmd /c 执行命令行。</summary>
    public static RunResult RunCmd(string cmd, int timeoutMs = 30000)
        => Run("cmd.exe", $"/c {cmd}", timeoutMs);
}
