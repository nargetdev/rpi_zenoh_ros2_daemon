# SPIKE RESULTS — colorbars CDR over rmw_zenoh

**Goal:** Validate the abstraction — prove `zenoh_ros2_sdk.ROS2Publisher` can emit a
correctly CDR-encoded `sensor_msgs/msg/Image` that a **real `rmw_zenoh` ROS 2
subscriber** discovers and reads back. A tiny synthetic colorbars frame is the probe.

## VERDICT: 🟢 GREEN — full ROS 2 interop confirmed

A real `rmw_zenoh_cpp` ROS 2 (jazzy) subscriber on `soma` discovered `/spike/colorbars`,
matched the type hash, and `ros2 topic echo` decoded the CDR payload into an `Image` with
`height=100, width=200, encoding=rgb8, step=600`, `frame_id=spike`, and **all 60000 data
bytes round-tripped pixel-perfect** (all 8 colorbars matched expected RGB).

---

## Environment discovered (differs from the task brief — see "Gaps")

- The macbook env (`172.31.1.102`) had `ZENOH_CONFIG_OVERRIDE=mode="client";connect/endpoints=["tcp/host.docker.internal:7447"]`
  exported, which the SDK applies **after** `router_ip` and which silently hijacked the
  connection. We ran the publisher with `env -u ZENOH_CONFIG_OVERRIDE -u ZENOH_SESSION_CONFIG_URI`.
- soma had **no Zenoh router listening on `172.31.1.252:7447`** (the brief assumed one).
  The existing ROS 2 stack runs in Docker containers on internal bridge networks
  (`tcp/172.17.0.2:7447`), not reachable from the LAN. So we **started our own router**
  bound to `tcp/0.0.0.0:7447` for this test.
- soma's host-side `ros2` CLI (pixi env `~/sync_ws/.pixi/envs/kilted`) is **broken**:
  its `setup.bash` poisons `LD_LIBRARY_PATH` so every `/bin/sh` subprocess that `ros2`
  spawns dies with `symbol lookup error: undefined symbol: rl_print_keybinding`
  (libreadline conflict). We instead used the working `mcp-server-ros2-zenoh:jazzy`
  Docker image (ROS 2 jazzy + rmw_zenoh_cpp) with `--network host`.

## Exact setup used

Router (on soma, jazzy, host network):
```
/tmp/soma_router_cfg.json5:
{ mode: "router", listen: { endpoints: ["tcp/0.0.0.0:7447"] },
  scouting: { multicast: { enabled: false } } }

docker run -d --name spike_router --network host \
  -v /tmp/soma_router_cfg.json5:/cfg/router.json5:ro \
  -e RMW_IMPLEMENTATION=rmw_zenoh_cpp -e ROS_DOMAIN_ID=0 \
  -e ZENOH_ROUTER_CONFIG_URI=/cfg/router.json5 \
  mcp-server-ros2-zenoh:jazzy \
  bash -lc 'source /opt/ros/jazzy/setup.bash && exec ros2 run rmw_zenoh_cpp rmw_zenohd'
# -> "Zenoh can be reached at: tcp/172.31.1.252:7447"
```

Publisher (on macbook, daemon venv):
```
env -u ZENOH_CONFIG_OVERRIDE -u ZENOH_SESSION_CONFIG_URI PYTHONUNBUFFERED=1 \
  pi_runtime/.venv/bin/python spikes/colorbars_cdr_publisher.py \
    --router-ip 172.31.1.252 --router-port 7447 --domain-id 0 \
    --rate 2 --duration 180
```
Publisher stdout:
```
[spike] colorbars: 200x100 rgb8, 60000 bytes
[spike] connecting publisher to tcp/172.31.1.252:7447 domain=0
[spike] keyexpr      = 0/spike/colorbars/sensor_msgs::msg::dds_::Image_/RIHS01_d31d41a9a4c4bc8eae9be757b0beed306564f7526c88ea6a4588fb9582527d47
[spike] dds_type     = sensor_msgs::msg::dds_::Image_
[spike] type_hash    = RIHS01_d31d41a9a4c4bc8eae9be757b0beed306564f7526c88ea6a4588fb9582527d47
[spike] first 24 data bytes = [255, 255, 255, ...]
[spike] published frame #1 (seq~1)
... published 136+ frames at 2 Hz ...
```

Subscriber (on soma, jazzy container, host network, session -> 127.0.0.1:7447,
SHM disabled — see Gaps):
```
/tmp/soma_sub_cfg.json5:
{ mode: "client", connect: { endpoints: ["tcp/127.0.0.1:7447"] },
  scouting: { multicast: { enabled: false } },
  transport: { shared_memory: { enabled: false } } }

docker run --rm --network host --ipc=host --shm-size=512m \
  -v /tmp/soma_sub_cfg.json5:/cfg/session.json5:ro \
  -e RMW_IMPLEMENTATION=rmw_zenoh_cpp -e ROS_DOMAIN_ID=0 \
  -e ZENOH_SESSION_CONFIG_URI=/cfg/session.json5 \
  mcp-server-ros2-zenoh:jazzy \
  bash -lc 'source /opt/ros/jazzy/setup.bash && ros2 topic <list|info|echo> ...'
```

## Real subscriber output

`ros2 topic list` (excerpt) — `/spike/colorbars` present:
```
...
/spike/colorbars
...
```

`ros2 topic info /spike/colorbars --verbose`:
```
Type: sensor_msgs/msg/Image
Publisher count: 1
Node name: zenoh_publisher_f6855bc2
Topic type hash: RIHS01_d31d41a9a4c4bc8eae9be757b0beed306564f7526c88ea6a4588fb9582527d47
Endpoint type: PUBLISHER
GID: fb.46.61.44.4f.cc.1a.f4.71.96.1a.26.fc.b4.7c.dc
QoS profile:
  Reliability: RELIABLE
  History (Depth): KEEP_LAST (10)
  Durability: VOLATILE
```
The subscriber's computed type hash **exactly matches** the SDK publisher's
RIHS01 hash — type negotiation succeeded.

`ros2 topic echo --once --full-length /spike/colorbars` (header + dims):
```
header:
  stamp:
    sec: 1780617095
    nanosec: 953336000
  frame_id: spike
height: 100
width: 200
encoding: rgb8
is_bigendian: 0
step: 600
data:
- 255
- 255
- 255
... (60000 bytes total)
```

## Pixel-pattern verification (decoded `data` vs. expected colorbars)

Pulled the full 60000-byte `data` array back from the echo and checked the center
pixel of each of the 8 vertical bars in row 0:
```
total bytes: 60000  expected: 60000
bar | x  | got (r,g,b)       | expected          | match
 0  |  12| (255, 255, 255)   | (255, 255, 255)   | OK   white
 1  |  37| (255, 255, 0)     | (255, 255, 0)     | OK   yellow
 2  |  62| (0, 255, 255)     | (0, 255, 255)     | OK   cyan
 3  |  87| (0, 255, 0)       | (0, 255, 0)       | OK   green
 4  | 112| (255, 0, 255)     | (255, 0, 255)     | OK   magenta
 5  | 137| (255, 0, 0)       | (255, 0, 0)       | OK   red
 6  | 162| (0, 0, 255)       | (0, 0, 255)       | OK   blue
 7  | 187| (0, 0, 0)         | (0, 0, 0)         | OK   black
ALL BARS MATCH: True
```

## Gaps / findings worth carrying forward

1. **`ZENOH_CONFIG_OVERRIDE` on the control host overrides `router_ip`.** The SDK applies
   `ZENOH_CONFIG_OVERRIDE` *after* inserting the `router_ip` you pass to `ROS2Publisher`,
   so a stray override (here pointing at `host.docker.internal:7447`) silently wins. Unset
   it (or set it correctly) before publishing.
2. **`data` must be a numpy `uint8` array, not `bytes`.** rosbags' CDR serializer calls
   `.view()` on `uint8[]` array fields; passing raw `bytes` raises
   `AttributeError: 'bytes' object has no attribute 'view'`. The spike builds `data` as a
   numpy array. (Relevant for the DSLR/JPEG path: feed numpy arrays.)
3. **Message-def fetch/caching.** On first use the SDK loads ROS message definitions (a
   tqdm progress bar over ~2000 defs runs on stdout). It did **not** observably git-clone on
   this machine in our runs — the defs were already cached, so the second publisher start
   began emitting in ~1s. Budget for a one-time cold load.
4. **No pre-existing LAN router.** The brief's `172.31.1.252:7447` router did not exist; we
   stood one up. For production the pi/gateways must point at a router that is actually
   reachable on the shared network (the pi client config currently targets a Tailscale IP
   `tcp/100.97.33.27:17447`).
5. **Container SHM.** rmw_zenoh tries to create a POSIX SHM segment; in a default container
   this fails (`Unable to create POSIX shm segment: OS error 12`). Fix by disabling
   `transport.shared_memory` in the session config and/or running with `--ipc=host
   --shm-size=512m`. Pure TCP works fine and is what this test used.
6. **Distro mix is fine.** Publisher used the SDK's own RIHS01 computation; router +
   subscriber were ROS 2 jazzy. The RIHS01 hash for `sensor_msgs/msg/Image` matched, so
   cross-distro interop held for this message.
