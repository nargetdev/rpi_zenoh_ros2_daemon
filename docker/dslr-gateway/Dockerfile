FROM ros:kilted

SHELL ["/bin/bash", "-c"]

# build-essential + curl + rustup: the pinned eclipse-zenoh==1.8.0 ships NO
# cp3x-abi3 manylinux x86_64 wheel (only a cp38 one, plus ARM/macOS abi3 wheels),
# so on this x86_64 + Python 3.12 mothership host pip must build it from source --
# give it a Rust toolchain and a C linker. On the real Pi targets the abi3 wheel
# exists. Mirrors ci/dslr, ci/gateway, and pico-ros-py/docker Dockerfiles.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3-pip \
        python3-pil \
        build-essential curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV CARGO_HOME=/usr/local/cargo \
    RUSTUP_HOME=/usr/local/rustup \
    PATH=/usr/local/cargo/bin:$PATH
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
    | sh -s -- -y --default-toolchain stable --profile minimal

RUN python3 -m pip install --break-system-packages "eclipse-zenoh==1.8.0"

WORKDIR /workspace/ros2_gateway
COPY ros2_gateway/src ./src

RUN source /opt/ros/kilted/setup.bash \
    && colcon build --symlink-install

COPY docker/dslr-gateway/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["dual-gateway"]
