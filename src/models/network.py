"""网络重置工具 — DNS刷新、Winsock重置、TCP/IP重置。"""

import subprocess


def flush_dns() -> bool:
    """刷新 DNS 缓存。"""
    try:
        subprocess.run(
            ["ipconfig", "/flushdns"],
            check=True, capture_output=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return True
    except Exception:
        return False


def reset_winsock() -> bool:
    """重置 Winsock 目录（需重启生效）。"""
    try:
        subprocess.run(
            ["netsh", "winsock", "reset"],
            check=True, capture_output=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return True
    except Exception:
        return False


def reset_tcp_ip() -> bool:
    """重置 TCP/IP 协议栈（需重启生效）。"""
    try:
        subprocess.run(
            ["netsh", "int", "ip", "reset"],
            check=True, capture_output=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return True
    except Exception:
        return False
