"""ProBalance CPU 调度引擎 — 自动检测 CPU 霸占进程并临时约束优先级。

核心逻辑（参考 Process Lasso ProBalance）：
1. 定期采样每个进程的 CPU 使用率
2. 通过 EWMA 趋势预测，在 CPU 即将超阈值时提前干预
3. 临时降低其优先级（+ 混合架构绑定 E-Core）
4. 系统负载恢复后自动还原
5. 关键进程白名单绝对保护
6. 使用 GetSystemCpuSetInformation 精确检测 P/E 核心拓扑
"""

import logging
import time
from collections import deque
from dataclasses import dataclass, field

import psutil

from src.models.anomaly import AnomalyDetector
from src.utils.constants import (
    PROTECTED_PROCESSES, AUDIO_PROCESSES,
    PROBALANCE_SYSTEM_THRESHOLD,
    PROBALANCE_PROCESS_THRESHOLD,
    PROBALANCE_SUSTAIN_SECONDS,
    PROBALANCE_MIN_CONSTRAIN_SECONDS,
    PROBALANCE_RESTORE_THRESHOLD,
)
from src.utils.winapi import get_foreground_window_pid, get_cpu_topology

logger = logging.getLogger(__name__)


@dataclass
class _ConstrainedProcess:
    """被约束的进程记录。"""
    pid: int
    name: str
    original_priority: int
    original_affinity: list[int] | None
    constrained_at: float  # time.monotonic()
    reason: str = "threshold"  # "threshold" 或 "anomaly"


@dataclass
class ProBalanceSnapshot:
    """ProBalance 单次采样结果。"""
    system_cpu: float = 0.0
    predicted_cpu: float = 0.0       # EWMA 预测值
    constrained_count: int = 0
    restored_count: int = 0
    actions: list[str] = field(default_factory=list)
    anomaly_actions: list[str] = field(default_factory=list)


class _TrendPredictor:
    """基于 EWMA 的 CPU 趋势预测器。

    通过指数加权移动平均跟踪趋势，计算变化率，
    预测未来 N 步的值，实现"预测性干预"而非"反应式干预"。
    """

    def __init__(self, alpha: float = 0.3, window: int = 10, lookahead: int = 2):
        self._alpha = alpha          # EWMA 平滑系数（越大越敏感）
        self._window = window        # 历史窗口大小
        self._lookahead = lookahead  # 向前预测步数
        self._history: deque[float] = deque(maxlen=window)
        self._ewma: float = 0.0
        self._rate: float = 0.0      # 变化率（每步）

    def update(self, value: float) -> float:
        """输入新样本，返回预测的未来值。"""
        prev_ewma = self._ewma
        if not self._history:
            self._ewma = value
        else:
            self._ewma = self._alpha * value + (1 - self._alpha) * self._ewma
        self._history.append(value)

        # 计算变化率（当前 EWMA 与上一次的差值）
        self._rate = self._ewma - prev_ewma

        # 预测：当前 EWMA + 变化率 × 前瞻步数，钳位到 [0, 100]
        predicted = self._ewma + self._rate * self._lookahead
        return max(0.0, min(100.0, predicted))

    def reset(self):
        self._history.clear()
        self._ewma = 0.0
        self._rate = 0.0


# 不应被约束的进程（白名单 = 受保护 + 音频 + 自身）
_WHITELIST = PROTECTED_PROCESSES | AUDIO_PROCESSES | {
    "system idle process", "registry", "memory compression",
    "dwm.exe", "explorer.exe", "searchhost.exe",
    "shellexperiencehost.exe", "startmenuexperiencehost.exe",
    "runtimebroker.exe", "fontdrvhost.exe",
    "python.exe", "pythonw.exe",  # 自身
}


class ProBalanceEngine:
    """ProBalance CPU 调度引擎。

    在 QTimer 驱动下定期调用 tick()，自动管理进程优先级。
    使用 GetSystemCpuSetInformation 精确检测 P/E 核心拓扑，
    通过 EWMA 趋势预测实现预测性干预。
    """

    def __init__(self):
        # 预热 psutil CPU 采样（首次调用返回 0.0）
        psutil.cpu_percent(interval=0)
        self._constrained: dict[int, _ConstrainedProcess] = {}
        self._over_threshold_since: dict[int, float] = {}
        # 精确 CPU 拓扑检测（通过 GetSystemCpuSetInformation）
        topo = get_cpu_topology()
        self._has_hybrid = topo.is_hybrid
        self._e_cores = topo.e_cores
        logger.info("ProBalance 初始化: hybrid=%s, P=%d, E=%d",
                     topo.is_hybrid, len(topo.p_cores), len(topo.e_cores))
        # 系统 CPU 趋势预测器
        self._sys_predictor = _TrendPredictor(alpha=0.3, window=10, lookahead=2)
        # 每进程 CPU 趋势预测器
        self._proc_predictors: dict[int, _TrendPredictor] = {}
        # 每进程 Z-score 异常检测器
        self._proc_anomalies: dict[int, AnomalyDetector] = {}

    def tick(
        self,
        system_threshold: int = PROBALANCE_SYSTEM_THRESHOLD,
        process_threshold: int = PROBALANCE_PROCESS_THRESHOLD,
        sustain_seconds: int = PROBALANCE_SUSTAIN_SECONDS,
        restore_threshold: int = PROBALANCE_RESTORE_THRESHOLD,
        anomaly_enabled: bool = True,
        z_threshold: float = 3.0,
        ewma_alpha: float = 0.3,
    ) -> ProBalanceSnapshot:
        """执行一次 ProBalance 采样与调度（预测性干预）。"""
        snap = ProBalanceSnapshot()
        now = time.monotonic()

        # 1. 采集系统 CPU 并计算预测值
        snap.system_cpu = psutil.cpu_percent(interval=0)
        snap.predicted_cpu = self._sys_predictor.update(snap.system_cpu)

        # 2. 实际负载低于恢复阈值 → 还原所有约束
        if snap.system_cpu < restore_threshold:
            snap.restored_count = self._restore_all(now)
            self._over_threshold_since.clear()
            self._proc_predictors.clear()
            self._proc_anomalies.clear()
            snap.constrained_count = len(self._constrained)
            return snap

        # 3. 预测值未达激活阈值 → 仅维持现有约束
        #    （用预测值而非实际值，实现提前干预）
        if snap.predicted_cpu < system_threshold:
            self._cleanup_dead()
            snap.constrained_count = len(self._constrained)
            return snap

        # 4. 预测高负载：扫描进程，约束霸占者
        fg_pid = get_foreground_window_pid()
        active_pids = set()

        for proc in psutil.process_iter(["pid", "name", "cpu_percent"]):
            try:
                pid = proc.info["pid"]
                name = (proc.info["name"] or "").lower()
                cpu = proc.info["cpu_percent"] or 0.0
                active_pids.add(pid)

                if name in _WHITELIST or pid == fg_pid:
                    self._over_threshold_since.pop(pid, None)
                    self._proc_predictors.pop(pid, None)
                    self._proc_anomalies.pop(pid, None)
                    continue
                if pid in self._constrained:
                    continue

                try:
                    nice = proc.nice()
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    continue
                if nice != psutil.NORMAL_PRIORITY_CLASS:
                    self._over_threshold_since.pop(pid, None)
                    continue

                # 用 EWMA 预测进程 CPU 趋势
                if pid not in self._proc_predictors:
                    self._proc_predictors[pid] = _TrendPredictor()
                predicted_cpu = self._proc_predictors[pid].update(cpu)

                # Z-score 异常检测
                if anomaly_enabled:
                    if pid not in self._proc_anomalies:
                        self._proc_anomalies[pid] = AnomalyDetector(
                            alpha=ewma_alpha, z_threshold=z_threshold,
                        )
                    z_score = self._proc_anomalies[pid].update(cpu)
                else:
                    z_score = 0.0

                # 原有逻辑：预测值超阈值 → 开始计时（预测性干预）
                if predicted_cpu >= process_threshold:
                    if pid not in self._over_threshold_since:
                        self._over_threshold_since[pid] = now
                    elif now - self._over_threshold_since[pid] >= sustain_seconds:
                        if self._constrain(proc, nice, "threshold"):
                            snap.actions.append(
                                f"已约束 {name}(PID {pid}) "
                                f"CPU={cpu:.0f}% 预测={predicted_cpu:.0f}%"
                            )
                # 新增：Z-score 异常检测触发（行为突变 + CPU > 5% + 系统负载高）
                elif (z_score > z_threshold and cpu > 5.0
                      and snap.system_cpu >= restore_threshold):
                    if self._constrain(proc, nice, "anomaly"):
                        snap.anomaly_actions.append(
                            f"异常检测约束 {name}(PID {pid}) "
                            f"CPU={cpu:.0f}% Z={z_score:.1f}"
                        )
                else:
                    self._over_threshold_since.pop(pid, None)

            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue

        # 清理已退出进程
        dead = [p for p in self._over_threshold_since if p not in active_pids]
        for p in dead:
            self._over_threshold_since.pop(p, None)
            self._proc_predictors.pop(p, None)
            self._proc_anomalies.pop(p, None)
        self._cleanup_dead()

        snap.constrained_count = len(self._constrained)
        return snap

    def _constrain(self, proc: psutil.Process, original_nice: int,
                   reason: str = "threshold") -> bool:
        """约束单个进程：降低优先级 + 绑定 E-Core。"""
        pid = proc.pid
        name = (proc.name() or "").lower()
        try:
            original_affinity = proc.cpu_affinity()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            original_affinity = None

        try:
            proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            return False

        # 混合架构：绑定到 E-Core
        if self._has_hybrid and self._e_cores:
            try:
                proc.cpu_affinity(self._e_cores)
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass

        self._constrained[pid] = _ConstrainedProcess(
            pid=pid, name=name,
            original_priority=original_nice,
            original_affinity=original_affinity,
            constrained_at=time.monotonic(),
            reason=reason,
        )
        self._over_threshold_since.pop(pid, None)
        logger.info("ProBalance: 约束 %s(PID %d)", name, pid)
        return True

    def _restore_all(self, now: float) -> int:
        """还原所有被约束的进程（尊重最短约束时间）。"""
        restored = 0
        to_remove = []
        for pid, info in self._constrained.items():
            if now - info.constrained_at < PROBALANCE_MIN_CONSTRAIN_SECONDS:
                continue
            ok = self._restore_one(pid, info)
            if ok:
                restored += 1
                to_remove.append(pid)
            # ok=False → 权限不足，保留记录下次重试
        for pid in to_remove:
            self._constrained.pop(pid, None)
        return restored

    def _restore_one(self, pid: int, info: _ConstrainedProcess) -> bool:
        """还原单个进程的优先级和亲和性。

        返回 True 表示可以移除记录（还原成功或进程已退出），
        返回 False 表示保留记录下次重试（权限不足）。
        """
        try:
            proc = psutil.Process(pid)
            proc.nice(info.original_priority)
            if info.original_affinity:
                proc.cpu_affinity(info.original_affinity)
            logger.info("ProBalance: 还原 %s(PID %d)", info.name, pid)
            return True
        except psutil.NoSuchProcess:
            return True  # 进程已退出，清除记录
        except psutil.AccessDenied:
            return False  # 权限不足，保留记录重试

    def _cleanup_dead(self):
        """清理已退出进程的约束记录和预测器。"""
        dead = []
        for pid in self._constrained:
            if not psutil.pid_exists(pid):
                dead.append(pid)
        for pid in dead:
            self._constrained.pop(pid, None)
            self._proc_predictors.pop(pid, None)
            self._proc_anomalies.pop(pid, None)

    def force_restore_all(self):
        """强制还原所有约束（不检查最短时间，用于关闭时）。"""
        for pid, info in list(self._constrained.items()):
            self._restore_one(pid, info)
        self._constrained.clear()
        self._over_threshold_since.clear()

    @property
    def constrained_processes(self) -> list[tuple[int, str, float, str]]:
        """返回当前被约束的进程列表：[(pid, name, 约束秒数, reason), ...]"""
        now = time.monotonic()
        return [
            (pid, info.name, round(now - info.constrained_at, 1), info.reason)
            for pid, info in self._constrained.items()
        ]
