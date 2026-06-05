# `live/` — live integration test against a real Zenoh router

Unlike [`ci/`](../ci/) and [`pico-ros-py/docker/`](../pico-ros-py/docker/), which
boot a hermetic `zenohd` of their own, this harness federates two containers
through an **external, already-running** Zenoh router (default
`172.31.1.102:7447`):

```
        live router  ──  zenohd on the LAN (172.31.1.102:7447)
          ▲                       ▲
          │                       │
   node-under-test           validator
   pico-ros-py               ROS 2 kilted + rmw_zenoh
   (NO ROS 2)                stock `ros2` CLI = THE GATE
   pub std_msgs/Int64        ros2 topic echo
   = time.time_ns()
```

* **`node-under-test`** — pure-zenoh `pico-ros-py` (no ROS 2). Runs
  [`scripts/run_epoch_pub.py`](../pico-ros-py/scripts/run_epoch_pub.py):
  one ROS 2 node `/node_under_test/node_under_test` publishing
  `std_msgs/msg/Int64` (= `time.time_ns()`, CDR-serialized) on
  `/node_under_test/node_under_test/epoch_ns`.
* **`validator`** — real ROS 2 (`ros:kilted-ros-base`) with `rmw_zenoh_cpp`.
  Runs only the stock `ros2` CLI and gates on its exit code.

## Run it

```sh
docker compose -f live/docker-compose.yml up --build \
    --abort-on-container-exit --exit-code-from validator
# exit 0  ==  "::::: ALL VALIDATE GATES PASSED :::::"
```

Point at a different router:

```sh
ROUTER_IP=10.0.0.5 ROUTER_PORT=7447 \
  docker compose -f live/docker-compose.yml up --build \
    --abort-on-container-exit --exit-code-from validator
```

Tear down: `docker compose -f live/docker-compose.yml down`.

Both containers use `network_mode: host` so they can reach the router on the
LAN directly (Linux hosts).

## What the validator asserts (`validator/echo.sh`)

| Gate | Requirement | Command (stock `ros2` CLI) |
|---|---|---|
| 1 | **heartbeat / discovery** | `ros2 node list` shows `/node_under_test/node_under_test` |
| 2 | **topic + CDR** | `ros2 topic echo node_under_test/node_under_test/epoch_ns` decodes a plausible nanosecond epoch |

The bare `ros2 topic echo node_under_test/node_under_test/epoch_ns` (type
auto-discovered from the graph) is tried first, exactly as requested; an
explicit `std_msgs/msg/Int64` is the fallback if discovery is slow.
