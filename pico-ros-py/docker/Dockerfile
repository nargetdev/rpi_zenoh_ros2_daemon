# SPDX-License-Identifier: Apache-2.0
# pico-ros-py runtime image: the "pi daemon" (param server) and the "master"
# (smoke test) both run from this image, as separate containers, exactly like
# the Raspberry Pi <-> Arch-master split over the LAN.
FROM python:3.12-slim

# git: the SDK clones ROS 2 message repos to build its type cache.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

ENV ZENOH_ROS2_SDK_CACHE=/opt/zenoh_ros2_sdk_cache \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install the package first (better layer caching for deps).
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY scripts ./scripts

# Bake the ROS 2 message/service type cache into the image so the running
# container needs no network (no git clone) to register rcl_interfaces types.
RUN python scripts/warm_cache.py

# Default role: the parameter server ("pi daemon"). Override in compose/CI.
CMD ["python", "scripts/run_params_server.py"]
