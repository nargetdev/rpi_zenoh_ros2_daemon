# SPDX-License-Identifier: Apache-2.0
#
# The validator: a REAL ROS 2 (kilted) node whose transport is pure Zenoh
# (rmw_zenoh_cpp -- no DDS). It runs the stock `ros2` CLI against the
# pico-ros-py "node under test" and gates the run on receiving its message.
#
# ROS 2 lives ONLY here. The node under test contains no ROS 2 -- just
# zenoh_ros2_sdk.
ARG ROS_DISTRO=kilted
FROM ros:${ROS_DISTRO}-ros-base
ARG ROS_DISTRO

# rmw_zenoh_cpp = the Zenoh middleware for ROS 2; ros-base ships the ros2 CLI.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ros-${ROS_DISTRO}-rmw-zenoh-cpp gettext-base \
    && rm -rf /var/lib/apt/lists/*

ENV ROS_DISTRO=${ROS_DISTRO} \
    RMW_IMPLEMENTATION=rmw_zenoh_cpp \
    PYTHONUNBUFFERED=1

COPY config/zenoh-session.json5.tmpl /config/zenoh-session.json5.tmpl
COPY validator/echo.sh /echo.sh
RUN chmod +x /echo.sh

# Source ROS, then run whatever command compose passes (default: the gate).
ENTRYPOINT ["/bin/bash", "-c", "source /opt/ros/$ROS_DISTRO/setup.bash && exec \"$@\"", "--"]
CMD ["/echo.sh"]
