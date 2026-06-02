#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""End-to-end smoke test for the pico-ros-py parameter server (the "master"
role in CI). Connects over the Zenoh router to the param server's node and
drives the full list/get/set/describe round-trip, asserting correctness.

Exits 0 on success, 1 on failure. This is the container that gates CI.
"""
import os
import sys
import time

from pico_ros_py import Node
from pico_ros_py import _rcl
from pico_ros_py.picoparams import ParameterType, ParameterValue


def _retry_call(client, *, attempts: int, delay: float, **fields):
    """Call a service, retrying until a non-None response or attempts run out.

    Tolerates the discovery window where the server isn't visible yet.
    """
    last = None
    for i in range(attempts):
        last = client.call(**fields)
        if last is not None:
            return last
        time.sleep(delay)
    return last


def main() -> int:
    router_ip = os.environ.get("ROUTER_IP", "127.0.0.1")
    router_port = int(os.environ.get("ROUTER_PORT", "7447"))
    target = os.environ.get("TARGET_NODE", "picoros")
    base = f"/{target}"

    node = Node("picoros_smoke", router_ip=router_ip, router_port=router_port)
    list_cli = node.create_client(f"{base}/list_parameters", "rcl_interfaces/srv/ListParameters")
    get_cli = node.create_client(f"{base}/get_parameters", "rcl_interfaces/srv/GetParameters")
    set_cli = node.create_client(f"{base}/set_parameters", "rcl_interfaces/srv/SetParameters")
    desc_cli = node.create_client(
        f"{base}/describe_parameters", "rcl_interfaces/srv/DescribeParameters"
    )

    try:
        # 1) list_parameters (also serves as discovery wait)
        print(f"[smoke] waiting for {base} ...", flush=True)
        listed = _retry_call(list_cli, attempts=40, delay=1.0, prefixes=[], depth=0)
        assert listed is not None, "list_parameters never responded (server not discovered)"
        names = list(listed.result.names)
        print(f"[smoke] list_parameters -> {names}", flush=True)
        assert "example.param1" in names, f"expected example.param1 in {names}"
        assert "example.greeting" in names

        # 2) get_parameters: initial values + types
        got = _retry_call(get_cli, attempts=5, delay=1.0, names=["example.param1", "example.greeting"])
        assert got is not None, "get_parameters timed out"
        p1, greet = got.values[0], got.values[1]
        assert int(p1.type) == int(ParameterType.INTEGER), f"param1 type={p1.type}"
        assert p1.integer_value == 10, f"param1 initial={p1.integer_value}"
        assert greet.string_value == "hello", f"greeting initial={greet.string_value!r}"
        print(f"[smoke] get -> param1={p1.integer_value} greeting={greet.string_value!r}", flush=True)

        # 3) set_parameters: valid update inside range
        upd = _rcl._parameter_msg("example.param1", ParameterValue(ParameterType.INTEGER, 7))
        res = _retry_call(set_cli, attempts=5, delay=1.0, parameters=[upd])
        assert res is not None, "set_parameters timed out"
        assert res.results[0].successful, f"set failed: {res.results[0].reason}"
        print("[smoke] set param1=7 OK", flush=True)

        # 4) get again: value must have changed
        got2 = _retry_call(get_cli, attempts=5, delay=1.0, names=["example.param1"])
        assert got2.values[0].integer_value == 7, f"after set, param1={got2.values[0].integer_value}"
        print("[smoke] verified param1==7", flush=True)

        # 5) set out of range: must be rejected with a reason
        bad = _rcl._parameter_msg("example.param1", ParameterValue(ParameterType.INTEGER, 9999))
        rej = _retry_call(set_cli, attempts=5, delay=1.0, parameters=[bad])
        assert rej is not None and not rej.results[0].successful, "out-of-range set was not rejected"
        assert "range" in rej.results[0].reason.lower(), f"reason={rej.results[0].reason!r}"
        print(f"[smoke] out-of-range rejected: {rej.results[0].reason!r}", flush=True)

        # 6) describe_parameters: descriptor + integer range echoed back
        desc = _retry_call(desc_cli, attempts=5, delay=1.0, names=["example.param1"])
        assert desc is not None, "describe_parameters timed out"
        d0 = desc.descriptors[0]
        assert d0.name == "example.param1"
        assert int(d0.type) == int(ParameterType.INTEGER)
        assert len(d0.integer_range) == 1 and d0.integer_range[0].to_value == 50
        print("[smoke] describe OK (range echoed)", flush=True)

        print("SMOKE OK", flush=True)
        return 0
    except AssertionError as exc:
        print(f"SMOKE FAIL: {exc}", flush=True)
        return 1
    finally:
        node.close()


if __name__ == "__main__":
    sys.exit(main())
