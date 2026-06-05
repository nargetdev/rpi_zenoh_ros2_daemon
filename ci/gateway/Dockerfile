# SPDX-License-Identifier: Apache-2.0
#
# The `ros2_gateway` relay image: a REAL ROS 2 install (rmw_zenoh_cpp transport)
# that colcon-builds and launches `gateway_node`. The node subscribes to the
# pi_runtime daemon's raw Zenoh frame blobs (`{frame_key_prefix}/**`) over its OWN
# `zenoh.open()` session and republishes them as native `sensor_msgs/msg/Image` +
# `sensor_msgs/msg/CompressedImage` onto the shared rmw_zenoh router.
#
# This path is "DEPRECATED for images" in production (the native one-hop path from
# pi_runtime is primary) but the CI brief names the gateway + its four params
# explicitly, so we build/launch/verify it as a reference relay (Gate 6).
#
# Build context is the REPO ROOT (parent of `ci/`) so we can COPY both the
# `ros2_gateway/` source tree and the CI config:
#   docker build -f ci/gateway/Dockerfile -t zenoh-dslr-gateway:ci .
#
# Mirrors `ci/verifier/Dockerfile` (ROS base + rmw_zenoh install + source-ROS
# ENTRYPOINT) and `ci/dslr/Dockerfile` (repo-root context + COPY ci/config/).
ARG ROS_DISTRO=jazzy
FROM ros:${ROS_DISTRO}-ros-base
ARG ROS_DISTRO

# rmw_zenoh_cpp = the Zenoh middleware for ROS 2; the message packages the node
# publishes (sensor-msgs) + colcon to build the package. The node imports `zenoh`
# and `PIL` DIRECTLY (not as ROS packages), and `ros2_gateway`'s package.xml lists
# them only as exec deps, so colcon won't install them -- pip them explicitly.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ros-${ROS_DISTRO}-rmw-zenoh-cpp \
        ros-${ROS_DISTRO}-sensor-msgs \
        ros-${ROS_DISTRO}-std-msgs \
        ros-${ROS_DISTRO}-std-srvs \
        python3-colcon-common-extensions \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Newer ROS base images ship a PEP 668 "externally managed" marker; the relay
# image is single-purpose so installing the two pure-Python deps system-wide is
# fine.
RUN pip install --no-cache-dir --break-system-packages \
        "eclipse-zenoh>=1.0,<2.0" "Pillow>=9.0.0"

ENV ROS_DISTRO=${ROS_DISTRO} \
    RMW_IMPLEMENTATION=rmw_zenoh_cpp \
    ZENOH_SESSION_CONFIG_URI=/config/zenoh-session.json5 \
    PYTHONUNBUFFERED=1

# colcon-build the gateway overlay. ros2_gateway/ already has the `src/` layout
# (src/zenoh_dslr_gateway), so colcon build run from /ws picks it up.
COPY ros2_gateway/ /ws/
RUN bash -c "source /opt/ros/$ROS_DISTRO/setup.bash && cd /ws && colcon build"

# The CI config: zenoh-client.json5 (the node's raw blob session, pointed at by
# the `zenoh_config_path` param), zenoh-session.json5 (the rmw_zenoh session),
# and the gateway param file binding the node to the CI camera.
COPY ci/config/ /config/

# Source ROS + the colcon overlay, then run whatever command compose passes.
ENTRYPOINT ["/bin/bash", "-c", "source /opt/ros/$ROS_DISTRO/setup.bash && source /ws/install/setup.bash && exec \"$@\"", "--"]
CMD ["ros2", "run", "zenoh_dslr_gateway", "gateway_node", "--ros-args", "--params-file", "/config/gateway-ci.params.yaml"]
