using System.Diagnostics;

namespace PrismCore.Models;

/// <summary>网络重置工具（对照 network.py）。</summary>
public static class NetworkTools
{
    public static bool FlushDns() => RunCmd("ipconfig", "/flushdns");

    public static bool ResetWinsock() => RunCmd("netsh", "winsock reset");

    public static bool ResetTcpIp() => RunCmd("netsh", "int ip reset");

    private static bool RunCmd(string exe, string args)
    {
        try
        {
            var psi = new ProcessStartInfo(exe, args)
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
