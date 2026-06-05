# `ci/` — self-contained ROS-2-interop harness (no ROS 2 in the daemons)

This is a hermetic, Docker-only CI/CD harness that **proves** that nodes built
on raw Zenoh logic (`zenoh_ros2_sdk` / `pico-ros-py`, **no ROS 2 installed**)
are indistinguishable from real ROS 2 nodes to the stock `ros2` CLI.

> **Two harnesses live here.** `compose.yml` + `verify.sh` is the fast **minimal
> smoke** (examples only, semantic checks). `compose.integration.yml` +
> `verify_integration.sh` is the **integration superset** that additionally
> brings up the **real `pi_runtime` DSLR daemon** (hardware mocked) and asserts
> **byte-level CDR** wire bytes, the real **SetBool** capture service, and the
> native **Image** topic. CI (`.github/workflows/ci.yml`) gates on the
> integration harness; the minimal one stays as a quick local check. See
> [The integration superset](#the-integration-superset) below.

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

---

## The integration superset

`compose.integration.yml` keeps the four minimal-smoke containers and adds two
more — **`dslr`**, the **real production `pi_runtime` daemon**, and **`gateway`**,
the colcon-built **`ros2_gateway`** relay (a real `rclpy` node that republishes
`dslr`'s raw Zenoh frame blobs as native `sensor_msgs/msg/Image` +
`CompressedImage` on `gw/` topics) — then gates on an extended verifier
(`verifier/verify_integration.sh`):

```
        router  ── raw zenohd (eclipse/zenoh)              no ROS 2, just zenoh
          ▲ ▲ ▲ ▲ ▲
   ┌──────┘ │ │ │ └──────────────────────────────────────────┐
 talker   params   dslr (REAL pi_runtime)   gateway          verifier
 /chatter /picoros • SetBool capture svc   (REAL rclpy)      ROS 2 + rmw_zenoh
 (no ROS2)(no ROS2)• Float32 core_temp     • republishes     stock ros2 CLI +
                   • native Image frames     Image on gw/*     rclpy raw=True
                   mock CaptureBackend +    • ros2 params     = THE GATE
                   mock thermal_zone file
                   (no ROS 2, no hardware)
```

Run it:

```sh
docker compose -f ci/compose.integration.yml up --build \
    --abort-on-container-exit --exit-code-from verifier
# exit 0  ==  "::::: ALL INTEGRATION GATES PASSED :::::"
```

Tear down: `docker compose -f ci/compose.integration.yml down -v`.

### The six gates (`verifier/verify_integration.sh`)

| Gate | Requirement | How |
|---|---|---|
| 1 | **enumeration** | `ros2 node list` shows `/pico_talker` + `/picoros`; `ros2 service list` shows `/dslr/ci_cam/capture`; `ros2 topic list` shows the core-temp topic |
| 2 | **topics + byte-level CDR** | `ros2 topic echo /chatter` **plus** `cdr_assert.py` asserts the exact CDR bytes (see below) |
| 3 | **parameters** | `ros2 param list/get/set` round-trip + **out-of-range reject** on `/picoros` (`describe` is *not* gated) |
| 4 | **service** | `ros2 service call /dslr/ci_cam/capture std_srvs/srv/SetBool "{data: true}"` returns `success=True` |
| 5 | **native Image (byte-level CDR)** | `cdr_assert.py --image` parses the raw FastCDR buffer on `/dslr/ci_cam/image_raw` and asserts width 640 / height 480 / `encoding: rgb8` / step 1920 — the exact bytes a native `rmw_zenoh_cpp` subscriber decodes (advisory unless `STRICT_IMAGE=1`, the default) |
| 6 | **ros2_gateway relay** | the `gateway` node is in the graph, its four declared string params round-trip via `ros2 param get/set`, and its republished Image (`/dslr/ci_cam/gw/image_raw`) echoes a 640×480 `rgb8` frame (step 1920) |

### Byte-level CDR — why `rclpy raw=True`

`ros2 topic echo` proves a message *decodes*; it does **not** prove the exact
bytes on the wire are what a native ROS 2 subscriber expects. `verifier/cdr_assert.py`
creates **raw** subscriptions (`create_subscription(..., raw=True)`), which hand
back the exact serialized **CDR buffer** the real discovery/transport path
produced, and asserts:

* **`std_msgs/msg/Float32`** core-temp — the `00 01 00 00` PLAIN-CDR
  little-endian encapsulation header, an 8-byte payload, and a `<f`-decoded value
  of **≈ 48.3** (the mock thermal-zone file holds `48300` → `48.3 °C`).
* **`std_msgs/msg/String`** `/chatter` — the same header, a `<I` length prefix, a
  **null-terminated** body decoding to the talker's greeting.
* **`sensor_msgs/msg/Image`** `/dslr/ci_cam/image_raw` — `cdr_assert.py --image`
  walks the FastCDR buffer (header → `frame_id` → height → width → encoding →
  `is_bigendian` → step → data length) and asserts width 640 / height 480 /
  `encoding: rgb8` / step 1920 and that the `data` array actually holds
  `step × height` bytes.

This is strictly stronger than `topic echo` and catches CDR / endianness /
type-hash / transport regressions a semantic check would miss.

### The hardware-mock boundary (the single swap point)

The whole daemon runs with its hardware **mocked behind the abstraction that
already ships** — `CaptureBackend` (`build_backend` dispatches on
`capture_backend.type`) and `CoreTempPublishConfig.thermal_zone_path`. The mock
boundary is **one config file**, [`config/dslr-mock.json`](config/dslr-mock.json):

* `capture_backend.type: "mock"` → `MockCaptureBackend` renders a date-stamped
  **640×480 `rgb8`** frame via Pillow (the default, `mock_synthesize: true`), so
  Gate 5's width/height/encoding/step assertions are meaningful; no `gphoto2`, no
  USB, no GPIO. Set `mock_synthesize: false` for the legacy 1×1 placeholder PNG;
  dimensions are tunable via `mock_width` / `mock_height`.
* `core_temp_publish.thermal_zone_path: "/config/thermal_zone_temp"` → a mock
  sysfs file (`48300`) instead of `/sys/class/thermal/thermal_zone0/temp`.

**Promote to real hardware with zero test-logic change:** in `dslr-mock.json`,
flip `capture_backend.type` to `"gphoto2"` (add the `port`), drop the
`thermal_zone_path` overrides so the real sysfs path is read, and mount the USB
camera into the `dslr` container. The verifier asserts the *same* services,
topics, and CDR bytes.

### Image build notes

The `dslr` image (`dslr/Dockerfile`) builds from the **repo root** (`context: ..`)
so it can `COPY` both `pi_runtime/` and `pico-ros-py/`. It installs no ROS 2;
`dslr/warm_cache.py` bakes the ROS 2 **message** type cache (`Float32`, `Image`,
`Header`, `Time`) into the image at build time so the running container is
offline-safe. The `SetBool` *service* is **not** warmed — the daemon supplies its
request/response definitions inline, so it never needs a clone.
