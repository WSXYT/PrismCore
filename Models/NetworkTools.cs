using PrismCore.Helpers;

namespace PrismCore.Models;

/// <summary>网络重置工具（对照 network.py）。</summary>
public static class NetworkTools
{
    public static bool FlushDns() => ProcessHelper.Run("ipconfig", "/flushdns", 15000).Success;

    public static bool ResetWinsock() => ProcessHelper.Run("netsh", "winsock reset", 15000).Success;

    public static bool ResetTcpIp() => ProcessHelper.Run("netsh", "int ip reset", 15000).Success;
}
