"""启动项管理 — 注册表 Run 键和任务计划程序。"""

import logging
import subprocess
import winreg

logger = logging.getLogger(__name__)
from dataclasses import dataclass


@dataclass
class StartupItem:
    name: str
    command: str
    source: str  # "registry" | "task"
    location: str
    enabled: bool


def list_startup_items() -> list[StartupItem]:
    """列举所有启动项。"""
    items: list[StartupItem] = []
    _scan_registry_run(items)
    _scan_task_scheduler(items)
    return items


def _scan_registry_run(items: list):
    run_keys = [
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", "HKCU"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", "HKLM"),
    ]
    for hive, path, prefix in run_keys:
        try:
            key = winreg.OpenKey(hive, path, 0, winreg.KEY_READ)
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                    i += 1
                    items.append(StartupItem(
                        name=name, command=str(value),
                        source="registry",
                        location=f"{prefix}\\{path}",
                        enabled=True,
                    ))
                except OSError:
                    break
            winreg.CloseKey(key)
        except OSError:
            pass


def _scan_task_scheduler(items: list):
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        for line in result.stdout.splitlines():
            parts = line.strip().strip('"').split('","')
            if len(parts) >= 3:
                name = parts[0].strip('"')
                status = parts[2].strip('"') if len(parts) > 2 else ""
                if name and not name.startswith("\\Microsoft"):
                    items.append(StartupItem(
                        name=name.rsplit("\\", 1)[-1],
                        command="(计划任务)",
                        source="task",
                        location=name,
                        enabled=status in ("Ready", "就绪", "Running", "正在运行"),
                    ))
    except Exception:
        logger.warning("查询计划任务失败", exc_info=True)
def toggle_startup_registry(item: StartupItem, enable: bool) -> bool:
    """启用或禁用注册表启动项。"""
    disabled_suffix = r"\AutorunsDisabled"
    try:
        if item.location.startswith("HKCU"):
            hive = winreg.HKEY_CURRENT_USER
        else:
            hive = winreg.HKEY_LOCAL_MACHINE

        base_path = item.location.split("\\", 1)[1]

        if enable:
            # 从 disabled 键移回 Run 键
            src_path = base_path + disabled_suffix
            dst_path = base_path
        else:
            # 从 Run 键移到 disabled 键
            src_path = base_path
            dst_path = base_path + disabled_suffix

        src_key = winreg.OpenKey(hive, src_path, 0, winreg.KEY_READ)
        val, typ = winreg.QueryValueEx(src_key, item.name)
        winreg.CloseKey(src_key)

        dst_key = winreg.OpenKey(hive, dst_path, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(dst_key, item.name, 0, typ, val)
        winreg.CloseKey(dst_key)

        del_key = winreg.OpenKey(hive, src_path, 0, winreg.KEY_SET_VALUE)
        winreg.DeleteValue(del_key, item.name)
        winreg.CloseKey(del_key)
        return True
    except OSError:
        return False


def toggle_startup_task(item: StartupItem, enable: bool) -> bool:
    """启用或禁用计划任务启动项。"""
    action = "/ENABLE" if enable else "/DISABLE"
    try:
        subprocess.run(
            ["schtasks", "/Change", "/TN", item.location, action],
            check=True, capture_output=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return True
    except Exception:
        logger.error("切换计划任务启动项失败: %s", item.location)
        return False
