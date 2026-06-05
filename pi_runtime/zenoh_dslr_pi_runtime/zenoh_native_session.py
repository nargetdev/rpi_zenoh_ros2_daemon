"""Force native ``zenoh_ros2_sdk`` sessions into CLIENT mode.

WHY THIS EXISTS
---------------
The SDK builds every ROS 2 session (Image publisher, core-temp publisher,
SetBool service server) through ``ZenohSession.__init__``, which loads the
bundled ``zenoh_ros2_sdk/config/default_session_config.json5``. That file is
``mode: "peer"`` with gossip + multicast scouting **enabled**. The SDK then
overrides only ``connect/endpoints`` (→ the router), never the mode — so the
sessions join the router as *peers*, not *clients*. A peer-mode publisher does
not declare interests the way the router's broker expects from a client, so the
router logs ``Unknown interest`` and drops ``sensor_msgs/msg/Image`` to the
native subscriber.

THE FIX
-------
``ZenohSession.__init__`` applies ``ZENOH_CONFIG_OVERRIDE`` *last* — after
loading the peer-default config and after the ``connect/endpoints`` insert (see
``zenoh_ros2_sdk/session.py:90-117``). So merging ``mode="client"`` (plus
disabled gossip/multicast scouting) into ``ZENOH_CONFIG_OVERRIDE`` before the
first ``ZenohSession`` is constructed deterministically wins over the peer
default. This module owns three override segments and forces them on; any other
user-supplied segments are preserved, ordered first.

The override string grammar (``;``-separated ``path=json5value`` pairs, later
wins, value parsed as JSON5) is defined by ``_parse_zenoh_config_override`` /
``_apply_zenoh_config_override`` in ``zenoh_ros2_sdk/session.py:26-85``.
"""
from __future__ import annotations

import logging
import os
from typing import MutableMapping

LOGGER = logging.getLogger("zenoh_dslr_pi_runtime.zenoh_native_session")

#: Override segments this module owns and forces. Match the SDK's JSON5 grammar:
#: ``mode`` value MUST be quoted (``"client"``); booleans are bare JSON5 ``false``.
MODE_SEGMENT = 'mode="client"'
GOSSIP_SEGMENT = "scouting/gossip/enabled=false"
MULTICAST_SEGMENT = "scouting/multicast/enabled=false"

#: Config paths (left of ``=``) we own. Any pre-existing segment with one of
#: these paths is dropped and replaced by our value, so ``mode="peer"`` from a
#: user override is forced back to ``client``.
_OWNED_PATHS = ("mode", "scouting/gossip/enabled", "scouting/multicast/enabled")

_OWNED_SEGMENTS = (MODE_SEGMENT, GOSSIP_SEGMENT, MULTICAST_SEGMENT)


def force_native_client_mode(env: MutableMapping[str, str] | None = None) -> str:
    """Merge CLIENT-mode segments into ``ZENOH_CONFIG_OVERRIDE``.

    Idempotent: any existing segment whose ``path`` (left of ``=``) is one we
    own is dropped and replaced by our value, then our segments are appended.
    All other user segments are preserved and ordered first. Returns the merged
    override string, which is also written back to ``env``.

    :param env: mapping to read/write (defaults to ``os.environ``).
    """
    if env is None:
        env = os.environ

    existing = env.get("ZENOH_CONFIG_OVERRIDE", "").strip()

    kept: list[str] = []
    for part in existing.split(";"):
        part = part.strip()
        if not part:
            continue
        path = part.split("=", 1)[0].strip()
        if path in _OWNED_PATHS:
            continue  # drop — we re-assert our own value below
        kept.append(part)

    merged = ";".join(kept + list(_OWNED_SEGMENTS))
    env["ZENOH_CONFIG_OVERRIDE"] = merged
    LOGGER.debug("forced native ROS 2 Zenoh sessions to CLIENT mode: %s", merged)
    return merged
