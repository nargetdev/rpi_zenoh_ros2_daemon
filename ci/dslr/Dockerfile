# SPDX-License-Identifier: Apache-2.0
#
# The REAL production daemon image: `pi_runtime` (the DSLR capture runtime) with
# its hardware mocked behind the existing `CaptureBackend` abstraction. There is
# NO ROS 2 in this image -- it is pure `zenoh_ros2_sdk` over raw Zenoh, exactly
# like what ships to the Raspberry Pis. ROS 2 lives ONLY in the `verifier`.
#
# Build context is the REPO ROOT (parent of `ci/`) so we can COPY both the
# `pi_runtime/` and `pico-ros-py/` source trees plus the CI config:
#   docker build -f ci/dslr/Dockerfile -t zenoh-dslr-pi-runtime:ci .
#
# Mirrors `pico-ros-py/docker/Dockerfile`: install git, set the SDK cache env,
# and warm the ROS 2 type cache at build time so the running container is
# offline-safe and never stalls a capture on a git clone.
FROM python:3.12-slim

# git: the SDK clones ROS 2 message repos to build its type cache (warm_cache.py).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

ENV ZENOH_ROS2_SDK_CACHE=/opt/zenoh_ros2_sdk_cache \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install both local packages explicitly. pi_runtime depends on pico-ros-py only
# for the OPT-IN exposure-params extra (not enabled here), but installing the
# local path first is harmless and future-proofs an exposure gate. Do NOT use
# `pip install ./pi_runtime[exposure]` -- that resolves pico-ros-py from PyPI
# (which does not exist); install the local path explicitly instead.
# pip pulls pi_runtime's deps (Pillow, numpy, eclipse-zenoh, zenoh-ros2-sdk,
# paho-mqtt); numpy is required because the SDK CDR serializer needs the Image
# uint8[] field as a numpy array.
COPY pico-ros-py/ ./pico-ros-py/
COPY pi_runtime/ ./pi_runtime/
RUN pip install --no-cache-dir ./pico-ros-py ./pi_runtime

# Bake the ROS 2 message/service type cache into the image (offline-safe runtime).
COPY ci/dslr/warm_cache.py ./warm_cache.py
RUN python warm_cache.py

# The CI config: dslr-mock.json (mock backend), zenoh-client.json5 (raw session),
# and the mock sysfs thermal-zone file the core-temp publisher reads.
COPY ci/config/ /config/

# Run the REAL daemon against the mock config. No ROS 2, no hardware, no gphoto2.
CMD ["python", "-m", "zenoh_dslr_pi_runtime.cli", "--config", "/config/dslr-mock.json"]
