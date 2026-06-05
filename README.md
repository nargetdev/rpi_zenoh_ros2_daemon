# Zenoh DSLR Capture Bridge

This repository targets an `rmw_zenoh` deployment. The Pi runtime publishes
captured frames **directly** as native `sensor_msgs/msg/Image`, so there is no
mothership relay in the image path:

- `pi_runtime/`: runs on a Raspberry Pi without ROS 2 installed, exposes a ROS 2 capture service through `zenoh_ros2_sdk`, and (when `ros2_publish` is enabled) publishes each captured frame as a native CDR-encoded `sensor_msgs/msg/Image` straight onto the shared rmw_zenoh router. It still also publishes the raw image bytes as a plain Zenoh blob for archival/other consumers.
- `ros2_gateway/`: **DEPRECATED for images** — the previous mothership relay that decoded Zenoh blobs into ROS image topics. The native one-hop path above replaces it. Retained only as reference and for the capture-service client harness.

Key properties:

- service call and acknowledgment travel as ROS 2 over Zenoh
- the image itself travels as a native `sensor_msgs/msg/Image` over the same router — one hop, no gateway
- Foxglove / any ROS 2 node consumes the standard `sensor_msgs/msg/Image` topic directly (confirmed live on `soma:8765`, `ws://172.31.1.252:8765`)
- the native publisher is failure-tolerant: a dead router never breaks capture, and the path is opt-in (`ros2_publish.enabled = false` by default)

## Layout

- `pi_runtime/`: transfer to the Raspberry Pi
- `ros2_gateway/`: transfer to the ROS 2 mothership
- `pico-ros-py/`: Python re-imagining of Pico-ROS (Node/pub/sub/services/params) on `zenoh_ros2_sdk` — first-class ROS 2 graph participation with no ROS 2 install
- `ci/`: **self-contained Docker CI/CD** that proves the no-ROS-2 daemons show up in `ros2 node list`, `ros2 topic echo`, and `ros2 param get/set` — federating only through a raw `zenohd`. See [`ci/README.md`](ci/README.md).
- `deploy/`: example Zenoh and `rmw_zenoh` configuration
- `docs/`: architecture notes and earlier bridge tradeoffs

## Validate the raw-Zenoh ↔ ROS 2 interop (one command)

```bash
docker compose -f ci/compose.yml up --build \
    --abort-on-container-exit --exit-code-from verifier
# exit 0 == "::::: ALL VERIFY GATES PASSED :::::"
```

Brings up a raw `zenohd` router, two pure-Zenoh `pico-ros-py` daemons (a talker
node and a parameter-server node, **no ROS 2 installed**), and one ROS 2 +
`rmw_zenoh` verifier that gates the run with the stock `ros2` CLI.

### Run the full integration gate locally

The smoke gate above proves the example daemons. The **integration** gate
additionally boots the REAL `pi_runtime` daemon (hardware mocked) and the
`ros2_gateway` relay, and asserts six gates in a single run:

```bash
ROS_DISTRO=jazzy docker compose -f ci/compose.integration.yml up --build \
    --abort-on-container-exit --exit-code-from verifier
# exit 0 == "::::: ALL INTEGRATION GATES PASSED :::::"
# On failure: docker compose -f ci/compose.integration.yml logs gateway dslr verifier
```

The verifier (`ci/verifier/verify_integration.sh`) gates on:

| Gate | Assertion |
|------|-----------|
| G1 | enumeration: example nodes + the real daemon's service/topic |
| G2 | byte-level CDR for `std_msgs/String` (`/chatter`) + `std_msgs/Float32` (core-temp) |
| G3 | `/picoros` param list/get/set + out-of-range reject |
| G4 | `SetBool` capture service returns `success=True` + JSON keys (`camera_id`, `request_id`) |
| G5 | **native** `sensor_msgs/Image` byte-level CDR: width 640 / height 480 / `rgb8` / step 1920 |
| G6 | **`ros2_gateway`** relay: its four declared params round-trip via `ros2 param get/set`, and its republished Image topic echoes a 640×480 `rgb8` frame (step 1920) |

The `gateway` service (`ci/gateway/Dockerfile`) colcon-builds and launches
`gateway_node` against `ci/config/gateway-ci.params.yaml`. It is a *verified
reference relay* — the native one-hop path (G5) remains the production image path;
the gateway is exercised in CI per the brief, not promoted.

The mock camera now renders a **date-stamped 640×480 `rgb8`** frame (today's date,
e.g. `2026-06-05`) via Pillow instead of a degenerate 1×1 PNG, so the downstream
width/height/encoding/step assertions are meaningful. Tune it through the mock
backend config knobs `mock_synthesize` (default `true`; set `false` for the legacy
1×1 placeholder), `mock_width` (default `640`), and `mock_height` (default `480`).

### Run the pure-Python unit suite

The unit suite includes a pgwaam MQTT online-pulse test that spawns its own broker;
install the `mosquitto` binary so it RUNS instead of skipping:

```bash
sudo apt-get install -y mosquitto   # Linux  (or: brew install mosquitto  on macOS)
cd pi_runtime && python -m pytest tests -v
```

## Data Flow

One-hop native path (no gateway in the image path):

```
   Raspberry Pi                         soma (rmw_zenoh router host)
 ┌──────────────────┐                 ┌────────────────────────────────┐
 │ pi_runtime       │  native         │  rmw_zenoh router (7447)        │
 │  capture(JPEG)   │  sensor_msgs/   │        │                       │
 │  -> downsample   │  msg/Image      │        ▼                       │
 │  -> ROS2Publisher├────────────────►│  foxglove_bridge (8765) ─► Foxglove
 │                  │   (CDR/Zenoh)   │  or any rmw_zenoh ROS 2 node    │
 └──────────────────┘                 └────────────────────────────────┘
```

1. A ROS 2 client calls a camera-specific service such as `/dslr/Canon_EOS_6D/capture`.
2. The Pi serves that service using `zenoh_ros2_sdk` and `std_srvs/srv/SetBool`.
3. The Pi captures a frame, then (when `ros2_publish.enabled`) PIL-decodes it to RGB, downsamples to fit `max_width`/`max_height`, and publishes a native `sensor_msgs/msg/Image` (`rgb8`) on the configured topic (default `/dslr/<camera_id>/image_raw`) via `zenoh_ros2_sdk.ROS2Publisher`, straight onto the shared rmw_zenoh router. It also still `put`s the raw image bytes on `dslr/<camera_id>/frames/<capture_id>` for archival/other consumers.
4. The SetBool response returns a JSON message with `capture_id`, `image_key`, encoding, and dimensions.
5. `foxglove_bridge` (or any `rmw_zenoh` ROS 2 node) on `soma` subscribes to that `sensor_msgs/msg/Image` topic and displays it directly — no relay, one hop. Confirmed live in Foxglove (`ws://172.31.1.252:8765`).

### `ros2_publish` config (shared contract)

The Pi config opt-in block (must match the ansible side exactly):

```json
"ros2_publish": {
  "enabled": false,
  "topic": null,
  "encoding": "rgb8",
  "max_width": 640,
  "max_height": 480,
  "domain_id": 0,
  "router_ip": "172.31.1.252",
  "router_port": 7447,
  "qos_reliability": "reliable",
  "qos_history_depth": 5
}
```

`topic` defaults to `/dslr/<camera_id>/image_raw`. A `0` for `max_width`/`max_height` disables that downsample axis.

## Why `std_srvs/SetBool`

The pure-ROS service surface now comes from `zenoh_ros2_sdk`, which is a much better fit for `rmw_zenoh` than the previous CycloneDDS plugin path.

For the first cut, the capture request uses `std_srvs/srv/SetBool` so the Pi can expose a standard ROS 2 service type without a ROS 2 install or custom interface packaging on the edge device. The request body is a simple `bool data`, and the response message carries JSON metadata for the capture acknowledgment.

If you later want richer request fields such as capture profile, exposure mode, or lens selection, the next step is to move from `Trigger` to a custom service type that `zenoh_ros2_sdk` can load cleanly in your deployment.

## Per-capture exposure via ROS 2 parameters

Exposure is **decoupled from the trigger**: set it any time, capture any time. When
`exposure.enabled` is on, the Pi runs a `pico-ros-py` parameter-server node that
exposes the gphoto2 exposure keys as standard ROS 2 parameters — so **no custom
service interface is needed on the caller**. The values are persistent; each
`SetBool` capture reads the current values and applies them via
`gphoto2 --set-config` immediately before the frame is taken (and echoes them
back in the capture metadata under `exposure`).

```bash
# set persistently, any time (these stick until changed):
ros2 param set /dslr_Canon_EOS_6D shutterspeed 1/250
ros2 param set /dslr_Canon_EOS_6D aperture 5.6
ros2 param set /dslr_Canon_EOS_6D iso 400
ros2 param list /dslr_Canon_EOS_6D     # shutterspeed, aperture, iso, autoexposuremode

# capture any time — uses whatever the params are right now:
ros2 service call /dslr/Canon_EOS_6D/capture std_srvs/srv/SetBool "{data: true}"
```

An empty value means "leave the camera as-is" (no `--set-config` issued for that
key). The node is opt-in and requires the `exposure` extra:

```bash
uv run --extra exposure python3 -m zenoh_dslr_pi_runtime.cli --config pi_runtime/config/id2-rpi4.json
```

```json
"exposure": {
  "enabled": true,
  "node_name": "dslr_Canon_EOS_6D",
  "router_ip": "172.31.1.252",
  "router_port": 7447,
  "domain_id": 0,
  "params": { "shutterspeed": "", "aperture": "", "iso": "", "autoexposuremode": "" }
}
```

The values must match the camera's gphoto2 choice lists (e.g. `gphoto2 --get-config shutterspeed`); for `shutterspeed`/`aperture`/`iso` to take effect the body should be in Manual (`autoexposuremode=Manual`). An invalid value makes that capture fail with the gphoto2 error.

## Quick Start

### Raspberry Pi

1. Install Python 3.10+.
2. Install `pi_runtime/` dependencies.
3. Edit `pi_runtime/config/pi.example.json`.
4. Run:

```bash
python3 -m zenoh_dslr_pi_runtime.cli --config pi_runtime/config/pi.example.json
```

The built-in `gphoto2` backend downloads the real image from the DSLR and stores a rolling local persistence buffer on the Pi. The buffer is pruned oldest-first to stay under the configured cap, for example `720 MB`.

### ROS 2 Mothership

1. Install ROS 2 with `rmw_zenoh_cpp`, `rclpy`, `sensor_msgs`, `std_msgs`, `std_srvs`, and `python3-pil`.
2. Copy `ros2_gateway/`.
3. Build and source:

```bash
cd ros2_gateway
colcon build
source install/setup.bash
```

4. Export the middleware:

```bash
export RMW_IMPLEMENTATION=rmw_zenoh_cpp
```

5. Launch the relay:

```bash
ros2 launch zenoh_dslr_gateway dslr_gateway.launch.py
```

For both cameras at once:

```bash
ros2 launch zenoh_dslr_gateway dual_dslr_gateway.launch.py
```

6. Trigger a capture:

```bash
ros2 run zenoh_dslr_gateway capture_client --ros-args -p service_name:=/dslr/Canon_EOS_6D/capture
```

## Notes

- The `gphoto2` backend assumes the camera is configured to save JPEGs if you want the relay to decode and publish `sensor_msgs/msg/Image`.
- The Pi runtime persists the captured files locally in a rolling buffer, with `persisted_path` included in the service response metadata.
- The previous `CycloneDDS + zenoh-plugin-ros2dds` adapter path is kept only as reference in `docs/`.
- See [docs/zenoh_ros2_sdk_assessment.md](/Users/mswhiskers/Documents/raspberry-dslr-service-zenoh/docs/zenoh_ros2_sdk_assessment.md:1) for the earlier comparison between the two middleware strategies.
