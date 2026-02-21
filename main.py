"""PrismCore — 智能PC优化与资源调度系统。"""

import ctypes
import sys

import sentry_sdk


def _sentry_before_send(event, hint):
    """过滤 Sentry 事件：丢弃没有堆栈的日志错误（用户环境问题）。"""
    # 非日志来源（如未捕获异常）直接放行
    if "log_record" not in hint:
        return event
    # 日志来源：只上报包含异常堆栈的（logger.exception）
    exc_info = hint.get("exc_info")
    if exc_info and exc_info[1] is not None:
        return event
    return None


sentry_sdk.init(
    dsn="https://b528527264ca6148a9b3c199f28232a8@o4510289605296128.ingest.de.sentry.io/4510924307562576",
    send_default_pii=True,
    enable_logs=True,
    traces_sample_rate=1.0,
    profile_session_sample_rate=1.0,
    before_send=_sentry_before_send,
)


def _is_already_running() -> bool:
    """通过 Windows Mutex 检测是否已有实例在运行。"""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    mutex = kernel32.CreateMutexW(None, True, "Global\\PrismCoreSingleInstance")
    # ERROR_ALREADY_EXISTS = 183
    return mutex == 0 or ctypes.get_last_error() == 183


def _ensure_admin():
    """若非管理员权限，通过 UAC 重新以管理员身份启动自身。"""
    if ctypes.windll.shell32.IsUserAnAdmin():
        return
    # ShellExecuteW 以 "runas" 动词重新启动
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable,
        " ".join(sys.argv), None, 1,
    )
    sys.exit(0)


def main():
    _ensure_admin()

    if _is_already_running():
        ctypes.windll.user32.MessageBoxW(
            0, "PrismCore 已经在运行中", "PrismCore", 0x40,
        )
        sys.exit(1)

    from src.app import create_app

    app, window = create_app()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
