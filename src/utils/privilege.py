"""Windows 权限提升工具。"""

import ctypes
import logging
from ctypes import wintypes

logger = logging.getLogger(__name__)


def is_admin() -> bool:
    """检查当前进程是否拥有管理员权限。"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def enable_privilege(privilege_name: str) -> bool:
    """为当前进程令牌启用指定的 Windows 特权。"""
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # 关键：设置正确的返回类型，避免 64 位句柄被截断
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL

    TOKEN_ADJUST_PRIVILEGES = 0x0020
    TOKEN_QUERY = 0x0008
    SE_PRIVILEGE_ENABLED = 0x00000002
    ERROR_NOT_ALL_ASSIGNED = 1300

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD),
                     ("HighPart", wintypes.LONG)]

    class LUID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Luid", LUID),
                     ("Attributes", wintypes.DWORD)]

    class TOKEN_PRIVILEGES(ctypes.Structure):
        _fields_ = [("PrivilegeCount", wintypes.DWORD),
                     ("Privileges", LUID_AND_ATTRIBUTES * 1)]

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(),
        TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
        ctypes.byref(token),
    ):
        logger.warning("OpenProcessToken 失败: %d", ctypes.get_last_error())
        return False

    luid = LUID()
    if not advapi32.LookupPrivilegeValueW(
        None, privilege_name, ctypes.byref(luid),
    ):
        logger.warning("LookupPrivilegeValueW(%s) 失败: %d",
                        privilege_name, ctypes.get_last_error())
        kernel32.CloseHandle(token)
        return False

    tp = TOKEN_PRIVILEGES()
    tp.PrivilegeCount = 1
    tp.Privileges[0].Luid = luid
    tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED

    result = advapi32.AdjustTokenPrivileges(
        token, False, ctypes.byref(tp),
        ctypes.sizeof(tp), None, None,
    )
    last_err = ctypes.get_last_error()
    kernel32.CloseHandle(token)

    if not result or last_err == ERROR_NOT_ALL_ASSIGNED:
        logger.warning("AdjustTokenPrivileges(%s) 失败: result=%s, err=%d",
                        privilege_name, result, last_err)
        return False

    logger.info("已启用特权: %s", privilege_name)
    return True
