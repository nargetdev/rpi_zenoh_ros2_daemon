"""Unit tests for the CLIENT-mode startup hook (no ROS 2 required)."""
from __future__ import annotations

from zenoh_dslr_pi_runtime.zenoh_native_session import force_native_client_mode


def test_empty_env_sets_all_three_segments():
    env: dict[str, str] = {}
    result = force_native_client_mode(env)
    assert 'mode="client"' in result
    assert "scouting/gossip/enabled=false" in result
    assert "scouting/multicast/enabled=false" in result
    assert env["ZENOH_CONFIG_OVERRIDE"] == result


def test_existing_user_override_preserved_and_appended():
    env = {"ZENOH_CONFIG_OVERRIDE": "transport/link/tx/lease=5000"}
    result = force_native_client_mode(env)
    assert "transport/link/tx/lease=5000" in result
    assert 'mode="client"' in result
    assert "scouting/gossip/enabled=false" in result
    assert "scouting/multicast/enabled=false" in result


def test_idempotent_on_double_call():
    env: dict[str, str] = {}
    force_native_client_mode(env)
    result = force_native_client_mode(env)
    assert result.count('mode="client"') == 1
    assert result.count("scouting/gossip/enabled=false") == 1
    assert result.count("scouting/multicast/enabled=false") == 1


def test_user_supplied_conflicting_mode_is_overridden_to_client():
    env = {"ZENOH_CONFIG_OVERRIDE": 'mode="peer"'}
    result = force_native_client_mode(env)
    assert 'mode="client"' in result
    assert 'mode="peer"' not in result
