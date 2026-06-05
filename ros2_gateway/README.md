> ## ⚠️ DEPRECATED for images
>
> This gateway's image relay is **superseded** by the native one-hop path. The Pi
> runtime (`pi_runtime/`) now publishes captured frames directly as native
> `sensor_msgs/msg/Image` via `zenoh_ros2_sdk.ROS2Publisher` onto the shared
> rmw_zenoh router, where `foxglove_bridge` / any ROS 2 node displays them with no
> relay in between. Enable it with the `ros2_publish` block in the Pi config.
>
> Confirmed live end-to-end (Foxglove on `soma:8765`, `ws://172.31.1.252:8765`).
> See the top-level `README.md` "Data Flow" and `spikes/RESULTS.md`.
>
> This workspace is retained only as reference and for the capture-service client
> harness. **Do not deploy it for image republication.**

# ROS 2 Gateway Workspace

This workspace contains a single ROS 2 package, `zenoh_dslr_gateway`.

It provides:

- a relay node that subscribes to plain Zenoh frame blobs and republishes ROS image topics
- a small service client harness that calls the remote Pi capture service

## Topics

- `/dslr/image_raw`
- `/dslr/image_compressed`

## Service

- client target: `/dslr/capture`

The expectation is that all ROS 2 nodes in this workspace run with `RMW_IMPLEMENTATION=rmw_zenoh_cpp`.
