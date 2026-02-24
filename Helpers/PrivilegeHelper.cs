using System.Runtime.InteropServices;

namespace PrismCore.Helpers;

/// <summary>权限提升工具（对照 privilege.py）。</summary>
public static class PrivilegeHelper
{
    public static bool IsAdmin() => NativeApi.IsUserAnAdmin();

    /// <summary>为当前进程令牌启用指定的 Windows 特权。</summary>
    public static bool EnablePrivilege(string privilegeName)
    {
        if (!NativeApi.OpenProcessToken(
                NativeApi.GetCurrentProcess(),
                NativeApi.TOKEN_ADJUST_PRIVILEGES | NativeApi.TOKEN_QUERY,
                out var token))
            return false;

        try
        {
            if (!NativeApi.LookupPrivilegeValueW(null, privilegeName, out var luid))
                return false;

            var tp = new NativeApi.TOKEN_PRIVILEGES
            {
                PrivilegeCount = 1,
                Luid = luid,
                Attributes = NativeApi.SE_PRIVILEGE_ENABLED
            };

            return NativeApi.AdjustTokenPrivileges(token, false, ref tp, (uint)Marshal.SizeOf(tp), 0, 0)
                   && Marshal.GetLastWin32Error() == 0;
        }
        finally
        {
            NativeApi.CloseHandle(token);
        }
    }
}
