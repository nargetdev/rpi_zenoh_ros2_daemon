# SPDX-License-Identifier: Apache-2.0
# pico-ros-py runtime image: the "pi daemon" (param server) and the "master"
# (smoke test) both run from this image, as separate containers, exactly like
# the Raspberry Pi <-> Arch-master split over the LAN.
FROM python:3.12-slim

# git: the SDK clones ROS 2 message repos to build its type cache.
# build-essential + curl: the pinned eclipse-zenoh==1.8.0 ships NO cp3x-abi3
# manylinux x86_64 wheel (only a cp38 one, plus ARM/macOS abi3 wheels), so on the
# x86_64 + Python 3.12 CI runner pip must build it from source. Provide a Rust
# toolchain (rustup) and a C linker so the exact 1.8.0 pin compiles. On the real
# Pi targets (aarch64/armv7l) the abi3 wheel exists, so no toolchain is needed there.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git build-essential curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV CARGO_HOME=/usr/local/cargo \
    RUSTUP_HOME=/usr/local/rustup \
    PATH=/usr/local/cargo/bin:$PATH
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
    | sh -s -- -y --default-toolchain stable --profile minimal

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
