# Project rules for AI agents

## Zenoh version alignment — pin 1.8.0

All ROS2-Zenoh middleware must align on Zenoh 1.8.0 — rmw_zenoh kilted (and
jazzy) pin zenoh-c 1.8.0 in `zenoh_cpp_vendor/CMakeLists.txt`; pin
`eclipse-zenoh` and any zenoh-pico build to 1.8.0 to avoid CDR/interest interop
failures. This project uses **kilted, not jazzy**.

## Native sessions must run in CLIENT mode

Native `zenoh_ros2_sdk` sessions (the Image publisher, core-temp publisher, and
SetBool service server) must connect to the router in `mode:"client"` — see
`pi_runtime/zenoh_dslr_pi_runtime/zenoh_native_session.py`. The SDK's bundled
`default_session_config.json5` is `mode:"peer"` with gossip scouting enabled;
peer mode causes the router to log `Unknown interest` and drop the
`sensor_msgs/msg/Image` to native subscribers. `force_native_client_mode()`
forces client mode via `ZENOH_CONFIG_OVERRIDE` before any session is opened.
