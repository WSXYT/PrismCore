"""EWMA + Z-score 在线异常检测器，支持 River 可选降级。"""

import math

try:
    from river.anomaly import HalfSpaceTrees as _HST
    _HAS_RIVER = True
except Exception:
    _HAS_RIVER = False


class AnomalyDetector:
    """EWMA + Z-score 在线异常检测器。

    使用 Welford 在线算法跟踪 EWMA 均值和方差，
    Z-score > z_threshold 时标记为异常。
    若 river 已安装，使用 HalfSpaceTrees 替代。
    """

    def __init__(self, alpha: float = 0.3, z_threshold: float = 3.0,
                 min_samples: int = 10, use_river: bool = True):
        self._alpha = alpha
        self._z_threshold = z_threshold
        self._min_samples = min_samples
        self._n = 0
        self._mean = 0.0
        self._var = 0.0
        self._last_z = 0.0
        # River 可选集成
        self._hst = None
        if use_river and _HAS_RIVER:
            self._hst = _HST(n_trees=10, height=6, window_size=50, seed=42)

    def update(self, value: float) -> float:
        """输入新样本，返回 Z-score（或 River 异常分数）。"""
        self._n += 1

        if self._hst is not None:
            score = self._hst.score_one({"x": value})
            self._hst.learn_one({"x": value})
            self._last_z = score * self._z_threshold / 0.5 if score > 0.5 else 0.0
            return self._last_z

        # EWMA + Welford 在线方差
        if self._n == 1:
            self._mean = value
            self._var = 0.0
            self._last_z = 0.0
            return 0.0

        delta1 = value - self._mean
        self._mean += self._alpha * delta1
        delta2 = value - self._mean
        self._var = (1 - self._alpha) * self._var + self._alpha * delta1 * delta2

        if self._n < self._min_samples or self._var <= 0:
            self._last_z = 0.0
            return 0.0

        std = math.sqrt(self._var)
        self._last_z = abs(value - self._mean) / std if std > 0 else 0.0
        return self._last_z

    @property
    def is_anomaly(self) -> bool:
        """当前样本是否为异常。"""
        return self._last_z > self._z_threshold
