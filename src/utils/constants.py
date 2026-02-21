"""全局常量定义。"""

APP_NAME = "PrismCore"
APP_VERSION = "1.0.0"
APP_AUTHOR = "PrismCore Team"

# 内存阈值
FREE_MEM_THRESHOLD_BYTES = 2 * 1024 ** 3  # 2 GB
STANDBY_RATIO_THRESHOLD = 0.25  # 总内存的 25%
COMMIT_RATIO_WARNING = 0.80  # 80%

# 磁盘阈值
DISK_CRITICAL_BYTES = 10 * 1024 ** 3  # 10 GB
LARGE_FILE_THRESHOLD_BYTES = 500 * 1024 ** 2  # 500 MB

# Electron 缓存特征目录
ELECTRON_CACHE_DIRS = [
    "Cache", "Code Cache", "GPUCache",
    "blob_storage", "Service Worker",
]
# Electron 安全目录（禁止删除）
ELECTRON_SAFE_DIRS = [
    "Local Storage", "Session Storage",
    "Cookies", "Preferences",
]

# 临时文件扩展名
TEMP_EXTENSIONS = {
    ".tmp", ".temp", ".log", ".old", ".bak",
    ".dmp", ".etl", ".chk",
}

# 受保护进程（禁止操作）
PROTECTED_PROCESSES = {
    "audiodg.exe", "csrss.exe", "smss.exe",
    "wininit.exe", "services.exe", "lsass.exe",
    "svchost.exe", "System",
}

# 音频相关进程（内存优化时保护）
AUDIO_PROCESSES = {
    "audiodg.exe", "audiosrv.exe",
    "spotify.exe", "music.ui.exe",
    "foobar2000.exe", "aimp.exe",
    "vlc.exe", "wmplayer.exe",
}

# 监控刷新间隔（毫秒）
MONITOR_INTERVAL_MS = 1500

# ── ProBalance CPU 调度默认参数 ──
# 系统总 CPU 超过此值才激活评估
PROBALANCE_SYSTEM_THRESHOLD = 60
# 单进程 CPU 超过此值才标记为候选
PROBALANCE_PROCESS_THRESHOLD = 10
# 进程持续超阈值时间（秒）才执行约束
PROBALANCE_SUSTAIN_SECONDS = 2
# 约束最短保持时间（秒），防止优先级抖动
PROBALANCE_MIN_CONSTRAIN_SECONDS = 3
# 系统 CPU 低于此值时恢复所有约束
PROBALANCE_RESTORE_THRESHOLD = 40
# 采样间隔（秒）
PROBALANCE_SAMPLE_INTERVAL = 1

# 页错误增量阈值
PAGE_FAULT_DELTA_THRESHOLD = 50000

# 注册表备份目录
import os
REGISTRY_BACKUP_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "PrismCore", "RegBackup",
)
