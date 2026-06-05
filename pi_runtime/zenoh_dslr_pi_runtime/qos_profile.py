from __future__ import annotations

from typing import Any


def build_qos_profile(qos_reliability: str, qos_history_depth: int) -> Any | None:
    """Map the shared contract's QoS fields onto a ``zenoh_ros2_sdk`` QoS profile.

    Best-effort: if the SDK QoS module is unavailable or the values are
    unexpected we fall back to the SDK default (``None``) rather than fail.
    """
    try:
        from zenoh_ros2_sdk.qos import QosProfile, QosReliability
    except Exception:  # pragma: no cover - SDK layout dependent
        return None
    reliability = (
        QosReliability.RELIABLE
        if str(qos_reliability).lower() == "reliable"
        else QosReliability.BEST_EFFORT
    )
    return QosProfile(
        reliability=reliability,
        history_depth=int(qos_history_depth),
    )
