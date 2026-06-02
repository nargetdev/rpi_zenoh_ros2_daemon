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
