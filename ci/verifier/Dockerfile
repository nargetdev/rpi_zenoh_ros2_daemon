# SPDX-License-Identifier: Apache-2.0
#
# The "master" / verifier container: a REAL ROS 2 install whose transport is
# pure Zenoh (rmw_zenoh_cpp) -- no DDS. It runs the stock `ros2` CLI
# (node list / topic echo / param get|set) against the pure-zenoh pico-ros-py
# daemons and gates the whole harness on the result.
#
# Note: ROS 2 lives ONLY in this verifier. The nodes under test
# (talker, params) contain no ROS 2 -- just zenoh_ros2_sdk.
ARG ROS_DISTRO=kilted
FROM ros:${ROS_DISTRO}-ros-base
ARG ROS_DISTRO

# rmw_zenoh_cpp = the Zenoh middleware for ROS 2. ros-base already provides the
# ros2 CLI (ros2cli / ros2topic / ros2node / ros2param).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ros-${ROS_DISTRO}-rmw-zenoh-cpp \
    && rm -rf /var/lib/apt/lists/*

ENV ROS_DISTRO=${ROS_DISTRO} \
    RMW_IMPLEMENTATION=rmw_zenoh_cpp \
    ZENOH_SESSION_CONFIG_URI=/config/zenoh-session.json5 \
    PYTHONUNBUFFERED=1

COPY config/zenoh-session.json5 /config/zenoh-session.json5
COPY verifier/verify.sh /verify.sh
RUN chmod +x /verify.sh

# Source ROS, then run whatever command compose passes (default: the gate).
ENTRYPOINT ["/bin/bash", "-c", "source /opt/ros/$ROS_DISTRO/setup.bash && exec \"$@\"", "--"]
CMD ["/verify.sh"]
