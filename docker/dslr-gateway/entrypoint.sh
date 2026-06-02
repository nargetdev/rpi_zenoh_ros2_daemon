#!/usr/bin/env bash
set -eo pipefail

source /opt/ros/kilted/setup.bash
source /workspace/ros2_gateway/install/setup.bash

export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_zenoh_cpp}"

case "${1:-dual-gateway}" in
  dual-gateway)
    ros2 run zenoh_dslr_gateway gateway_node --ros-args \
      -r __node:=zenoh_dslr_gateway_6d \
      -p camera_id:=Canon_EOS_6D \
      -p frame_key_prefix:=dslr/Canon_EOS_6D/frames \
      -p image_topic:=/dslr/Canon_EOS_6D/image_raw \
      -p compressed_topic:=/dslr/Canon_EOS_6D/image_compressed \
      -p zenoh_config_path:=/workspace/deploy/gateway/zenoh-client-local.json5 &
    pid_6d=$!

    ros2 run zenoh_dslr_gateway gateway_node --ros-args \
      -r __node:=zenoh_dslr_gateway_m50 \
      -p camera_id:=Canon_EOS_M50 \
      -p frame_key_prefix:=dslr/Canon_EOS_M50/frames \
      -p image_topic:=/dslr/Canon_EOS_M50/image_raw \
      -p compressed_topic:=/dslr/Canon_EOS_M50/image_compressed \
      -p zenoh_config_path:=/workspace/deploy/gateway/zenoh-client-local.json5 &
    pid_m50=$!

    trap 'kill "${pid_6d}" "${pid_m50}" 2>/dev/null || true; wait || true' INT TERM
    wait -n "${pid_6d}" "${pid_m50}"
    ;;
  *)
    exec "$@"
    ;;
esac
