# `ci/` — self-contained ROS-2-interop harness (no ROS 2 in the daemons)

This is a hermetic, Docker-only CI/CD harness that **proves** that nodes built
on raw Zenoh logic (`zenoh_ros2_sdk` / `pico-ros-py`, **no ROS 2 installed**)
are indistinguishable from real ROS 2 nodes to the stock `ros2` CLI.

A single `docker compose up` brings up four containers and gates the run on a
real `ros2` verifier:

```
        router  ── raw zenohd (eclipse/zenoh:1.x)         no ROS 2, just zenoh
          ▲ ▲ ▲
          │ │ └──────────────────────────────┐
   ┌──────┘ └─────────┐                       │
 talker            params                  verifier
 pico-ros-py       pico-ros-py            ROS 2 + rmw_zenoh
 /pico_talker      /picoros               stock `ros2` CLI = THE GATE
 pub /chatter      parameter server
 (no ROS 2)        (no ROS 2)             (ROS 2 lives ONLY here)
```

* **`router`** — a plain `zenohd` (the `eclipse/zenoh` image). The only thing on
  the data path. No ROS 2, no DDS. This is the "raw zenohd logic" everything
  federates through.
* **`talker`** / **`params`** — the daemons under test. Pure Python on
  `zenoh_ros2_sdk`; **no ROS 2 install**. `talker` is one node publishing
  `/chatter`; `params` is one node serving the `rcl_interfaces` parameter API.
  Their Zenoh liveliness tokens are their ROS 2 graph "heartbeat".
* **`verifier`** — a real ROS 2 (`ros:kilted-ros-base`) whose middleware is
  `rmw_zenoh_cpp` (raw Zenoh transport, no DDS). It runs only the stock `ros2`
  CLI and **gates the whole run on its exit code**.

## Run it

```sh
docker compose -f ci/compose.yml up --build \
    --abort-on-container-exit --exit-code-from verifier
# exit 0  ==  "::::: ALL VERIFY GATES PASSED :::::"
```

Tear down: `docker compose -f ci/compose.yml down -v`.

## What the verifier asserts (`verifier/verify.sh`)

| Gate | Requirement | Command (stock `ros2` CLI) |
|---|---|---|
| 1 | **heartbeat / enumeration** | `ros2 node list` shows `/pico_talker` **and** `/picoros` |
| 2 | **topics** | `ros2 topic echo /chatter` receives the talker's message |
| 3 | **parameters** | `ros2 param list/get/set /picoros` round-trips `example.param1` 10 → 7 |

Example passing output:

```
[verify] ros2 node list ->
    /pico_talker
    /picoros
[verify] GATE 1 ok: both daemon nodes enumerated (heartbeat visible)
[verify] ros2 topic echo /chatter ->
    data: 'hello from pico-ros-py: 4'
[verify] GATE 2 ok: topic message received over raw zenoh
[verify] ros2 param get /picoros example.param1 -> Integer value is: 10
[verify] ros2 param set /picoros example.param1 7 -> Set parameter successful
[verify] ros2 param get (after set) -> Integer value is: 7
[verify] GATE 3 ok: param get/set round-trip over raw zenoh
::::: ALL VERIFY GATES PASSED :::::
```

## How the verifier reaches the raw router (two gotchas, both solved here)

`rmw_zenoh` normally spawns its own `rmw_zenohd` and discovers via gossip. We
override its **session** config ([`config/zenoh-session.json5`](config/zenoh-session.json5))
via `ZENOH_SESSION_CONFIG_URI` so the ROS 2 session connects straight to our
`router` container instead. That minimal config also dodges two real-world
breakages:

1. **Config schema drift** — some shipped `DEFAULT_RMW_ZENOH_SESSION_CONFIG.json5`
   files contain a `shared_memory.transport_optimization` field the bundled
   zenoh-c can't parse. A *minimal* config avoids it: unknown fields fail,
   missing ones just default.
2. **SHM in Docker** — zenoh-c's POSIX shared-memory probe fails in Docker's
   tiny `/dev/shm` (`OS error 12`). We set `transport.shared_memory.enabled:
   false` (TCP-only here anyway) and also bump `shm_size` on the verifier.

## Knobs

| Variable | Default | Effect |
|---|---|---|
| `ROS_DISTRO` (build arg) | `kilted` | ROS 2 distro for the verifier image |
| `ZENOH_IMAGE` | `eclipse/zenoh:latest` | the raw router image |
| per-service env in `compose.yml` | — | node names, topic, param name/values |

## Why this is meaningful

The daemons never import ROS 2, never run a DDS stack, and never link `rcl`.
Everything you see in `ros2 node list / topic echo / param get|set` is produced
by Zenoh liveliness tokens and CDR payloads over a plain `zenohd`. That is the
whole premise of running ROS 2 graph participants on a Raspberry Pi (or any
CPython host) with nothing but Zenoh.
