# `zenoh_ros2_sdk` Assessment

This project has two plausible implementation tracks.

## Track A: Keep `CycloneDDS + zenoh-plugin-ros2dds`

This is the track implemented in the repository right now.

### Shape

- Raspberry Pi runs a Zenoh-native queryable and publishes raw frame bytes.
- Mothership runs ROS 2 with CycloneDDS plus `zenoh-plugin-ros2dds`.
- A small ROS 2 gateway node translates:
  - ROS 2 service call -> Zenoh query
  - Zenoh frame bytes -> ROS 2 image topics

### Why it fits the current requirement

- It preserves your current mothership middleware stack.
- It does not require a ROS 2 install on the Pi.
- It avoids reimplementing CycloneDDS service framing on the Pi.

### Cost

- We keep custom adapter code on the mothership.
- The Pi queryable is not itself directly visible as a ROS 2 service server.

## Track B: Pivot to `rmw_zenoh + zenoh_ros2_sdk`

This is the cleaner pure-Zenoh path if you can change the ROS 2 middleware choice.

### What the SDK explicitly claims

The `zenoh_ros2_sdk` README says:

- pure Python applications can publish and subscribe to ROS 2 topics over Zenoh without a ROS 2 install
- publishers and subscribers appear in ROS tooling
- services are supported via `ROS2ServiceServer` and `ROS2ServiceClient`
- the SDK works with existing ROS 2 nodes using `rmw_zenoh`

Its getting-started guide also demonstrates running:

```bash
ros2 run rmw_zenoh_cpp rmw_zenohd
```

before using the SDK.

### Why that is interesting here

If the mothership ROS 2 nodes use `rmw_zenoh`, then the Pi could likely:

- expose the capture service directly with `ROS2ServiceServer`
- publish `sensor_msgs/msg/CompressedImage` directly with `ROS2Publisher`
- possibly publish `sensor_msgs/msg/Image` too, if raw decode on the Pi is acceptable

That would collapse much of the custom gateway logic in this repo.

### Why it is not the default here

Your original requirement explicitly called out:

- a ROS 2 master node running CycloneDDS
- `zenoh-plugin-ros2dds` or the DDS bridge on the mothership router

The SDK documentation does not currently claim compatibility with that stack. Its wording is specifically about `rmw_zenoh`.

## Recommendation

The repository now follows Track B by default:

- the Pi uses `zenoh_ros2_sdk` for the ROS 2 service surface
- the mothership uses `rmw_zenoh`
- the gateway only relays plain Zenoh frame blobs into ROS image topics

## Suggested Next Pivot

If you want to explore the SDK path next, the most useful follow-up is:

1. Build a tiny Pi-side `ROS2ServiceServer` using `zenoh_ros2_sdk`.
2. Publish a `sensor_msgs/msg/CompressedImage` topic from the same Pi process.
3. Verify visibility from a mothership ROS 2 node running `rmw_zenoh`.
4. Only after that, decide whether to keep or delete the custom gateway layer.
