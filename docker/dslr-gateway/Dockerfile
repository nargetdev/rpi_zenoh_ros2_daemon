FROM ros:kilted

SHELL ["/bin/bash", "-c"]

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3-pip \
        python3-pil \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --break-system-packages "eclipse-zenoh>=1.0,<2.0"

WORKDIR /workspace/ros2_gateway
COPY ros2_gateway/src ./src

RUN source /opt/ros/kilted/setup.bash \
    && colcon build --symlink-install

COPY docker/dslr-gateway/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["dual-gateway"]
