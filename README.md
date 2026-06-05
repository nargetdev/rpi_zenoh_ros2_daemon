# Zenoh DSLR Capture Bridge

This repository targets an `rmw_zenoh` deployment with two code paths:

- `pi_runtime/`: runs on a Raspberry Pi without ROS 2 installed, exposes a ROS 2 capture service through `zenoh_ros2_sdk`, and publishes the captured image bytes as a plain Zenoh blob
- `ros2_gateway/`: runs on the mothership, calls the remote ROS 2 service, subscribes to the plain Zenoh frame blobs, and republishes ROS image topics for Foxglove

This keeps your original split:

- service call and acknowledgment travel as ROS 2 over Zenoh
- binary image transfer travels separately as raw Zenoh data
- Foxglove consumes standard ROS 2 image topics on the mothership

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

## Data Flow

1. A mothership ROS 2 client calls a camera-specific service such as `/dslr/Canon_EOS_6D/capture`.
2. The Pi serves that service using `zenoh_ros2_sdk` and `std_srvs/srv/SetBool`.
3. The Pi captures a frame and publishes compressed image bytes on a camera-specific Zenoh key such as `dslr/Canon_EOS_6D/frames/<capture_id>`.
4. The SetBool response returns a JSON message with `capture_id`, `image_key`, encoding, and dimensions.
5. The mothership relay subscribes to the camera-specific frame prefix and republishes:
   - `/dslr/Canon_EOS_6D/image_raw` as `sensor_msgs/msg/Image`
   - `/dslr/Canon_EOS_6D/image_compressed` as `sensor_msgs/msg/CompressedImage`

## Why `std_srvs/SetBool`

The pure-ROS service surface now comes from `zenoh_ros2_sdk`, which is a much better fit for `rmw_zenoh` than the previous CycloneDDS plugin path.

For the first cut, the capture request uses `std_srvs/srv/SetBool` so the Pi can expose a standard ROS 2 service type without a ROS 2 install or custom interface packaging on the edge device. The request body is a simple `bool data`, and the response message carries JSON metadata for the capture acknowledgment.

If you later want richer request fields such as capture profile, exposure mode, or lens selection, the next step is to move from `Trigger` to a custom service type that `zenoh_ros2_sdk` can load cleanly in your deployment.

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
