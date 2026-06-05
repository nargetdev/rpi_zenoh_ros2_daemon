#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# The INTEGRATION CI gate -- a superset of `verify.sh`. Uses ONLY the stock ros2
# CLI + an rclpy raw subscriber (transport = rmw_zenoh, i.e. raw zenoh) to prove
# that the pure-zenoh daemons -- including the REAL production `pi_runtime`
# daemon (hardware mocked) -- are first-class ROS 2 citizens, down to the wire
# bytes:
#
#   1 enumeration  : `ros2 service list` / `ros2 topic list` show the real
#                    daemon's service + core-temp topic; nodes for the examples
#   2 topics + CDR : `ros2 topic echo /chatter` + `cdr_assert.py` (byte-level
#                    CDR header / endianness / field bytes for String + Float32)
#   3 parameters   : `ros2 param list/get/set` + out-of-range reject on /picoros
#   4 service      : `ros2 service call` on the REAL std_srvs/srv/SetBool capture,
#                    asserting success=True AND the JSON metadata keys it returns
#   5 image (CDR)  : native sensor_msgs/msg/Image byte-level CDR via cdr_assert.py
#                    (width 640 / height 480 / encoding rgb8 / step 1920)
#   6 gateway      : the ros2_gateway relay node -- param get/set round-trip on its
#                    four declared params + its REPUBLISHED Image topic echo
#                    (sensor_msgs/msg/Image, 640/480/rgb8/1920)
#
# Exit 0 == all gates pass. Any failure exits non-zero and aborts the harness.
set -uo pipefail

# -- example-node knobs (pico-ros-py talker + param server) -------------------
TALKER_NODE="${TALKER_NODE:-/pico_talker}"
PARAMS_NODE="${PARAMS_NODE:-/picoros}"
TOPIC="${TOPIC:-/chatter}"
PARAM="${PARAM:-example.param1}"
PARAM_NEW="${PARAM_NEW:-7}"
PARAM_INIT="${PARAM_INIT:-10}"
PARAM_BAD="${PARAM_BAD:-9999}"

# -- real pi_runtime daemon knobs --------------------------------------------
CAPTURE_SERVICE="${CAPTURE_SERVICE:-/dslr/ci_cam/capture}"
CORE_TEMP_TOPIC="${CORE_TEMP_TOPIC:-/pgwaam/ci_dslr/online/core_temp}"
IMAGE_TOPIC="${IMAGE_TOPIC:-/dslr/ci_cam/image_raw}"
STRICT_IMAGE="${STRICT_IMAGE:-1}"

# Expected native + gateway Image dims (the 640x480 rgb8 synthesized mock frame).
IMAGE_W="${IMAGE_W:-640}"
IMAGE_H="${IMAGE_H:-480}"
IMAGE_STEP="${IMAGE_STEP:-1920}"

# -- ros2_gateway relay knobs (Gate 6) ---------------------------------------
GATEWAY_NODE="${GATEWAY_NODE:-/zenoh_dslr_gateway}"
GATEWAY_IMAGE_TOPIC="${GATEWAY_IMAGE_TOPIC:-/dslr/ci_cam/gw/image_raw}"
GATEWAY_COMPRESSED_TOPIC="${GATEWAY_COMPRESSED_TOPIC:-/dslr/ci_cam/gw/image_compressed}"

DISCOVERY_TRIES="${DISCOVERY_TRIES:-40}"   # ~40 * 2s = up to 80s for discovery

log()  { echo "[verify] $*"; }
fail() { echo "[verify] FAIL: $*" >&2; echo "::::: INTEGRATION FAILED :::::"; exit 1; }

log "RMW=$RMW_IMPLEMENTATION  session_cfg=$ZENOH_SESSION_CONFIG_URI"
log "waiting for the Zenoh graph to converge ..."

# ---------------------------------------------------------------------------
# 1) ENUMERATION -- the example nodes appear in `ros2 node list`, AND the REAL
#    daemon's service + core-temp topic appear in the graph. (The SDK gives raw
#    endpoints their own graph identity, so we assert the daemon's SERVICE/TOPIC
#    presence rather than hard-asserting a single `dslr` node name.)
# ---------------------------------------------------------------------------
nodes=""; services=""; topics=""
for i in $(seq 1 "$DISCOVERY_TRIES"); do
  nodes="$(ros2 node list 2>/dev/null)"
  services="$(ros2 service list 2>/dev/null)"
  topics="$(ros2 topic list 2>/dev/null)"
  if grep -qx "$TALKER_NODE" <<<"$nodes" \
     && grep -qx "$PARAMS_NODE" <<<"$nodes" \
     && grep -qx "$CAPTURE_SERVICE" <<<"$services" \
     && grep -qx "$CORE_TEMP_TOPIC" <<<"$topics"; then
    break
  fi
  sleep 2
done
log "ros2 node list ->";    echo "$nodes"    | sed 's/^/    /'
log "ros2 service list ->"; echo "$services" | sed 's/^/    /'
log "ros2 topic list ->";   echo "$topics"   | sed 's/^/    /'
grep -qx "$TALKER_NODE" <<<"$nodes"        || fail "node $TALKER_NODE not in 'ros2 node list'"
grep -qx "$PARAMS_NODE" <<<"$nodes"        || fail "node $PARAMS_NODE not in 'ros2 node list'"
grep -qx "$CAPTURE_SERVICE" <<<"$services" || fail "service $CAPTURE_SERVICE not in 'ros2 service list' (real daemon down?)"
grep -qx "$CORE_TEMP_TOPIC" <<<"$topics"   || fail "topic $CORE_TEMP_TOPIC not in 'ros2 topic list' (real daemon down?)"
log "GATE 1 ok: example nodes + REAL daemon service/topic enumerated"

# ---------------------------------------------------------------------------
# 2) TOPICS + BYTE-LEVEL CDR -- echo the /chatter String, then assert the EXACT
#    CDR wire bytes for String (/chatter) AND Float32 (core-temp) via rclpy raw.
# ---------------------------------------------------------------------------
echoed=""
for i in $(seq 1 10); do
  echoed="$(timeout 10 ros2 topic echo --once "$TOPIC" std_msgs/msg/String 2>/dev/null)"
  grep -q "hello from pico-ros-py" <<<"$echoed" && break
  sleep 2
done
log "ros2 topic echo $TOPIC ->"; echo "$echoed" | sed 's/^/    /'
grep -q "hello from pico-ros-py" <<<"$echoed" || fail "no message echoed on $TOPIC"

log "running byte-level CDR assertions (cdr_assert.py, rclpy raw=True) ..."
CORE_TEMP_TOPIC="$CORE_TEMP_TOPIC" CHATTER_TOPIC="$TOPIC" \
  python3 /cdr_assert.py || fail "byte-level CDR assertion failed (see [cdr] lines above)"
log "GATE 2 ok: topic echo + byte-level CDR (String + Float32) over raw zenoh"

# ---------------------------------------------------------------------------
# 3) PARAMETERS -- list, get-initial, set, get-after-set, out-of-range reject.
#    (`ros2 param describe` is deliberately NOT gated: nested-message service
#    type-hash mismatch in the SDK -- see live/validator/echo.sh.)
# ---------------------------------------------------------------------------
listed=""
for i in $(seq 1 15); do
  listed="$(timeout 12 ros2 param list "$PARAMS_NODE" 2>/dev/null)"
  grep -q "$PARAM" <<<"$listed" && break
  sleep 2
done
log "ros2 param list $PARAMS_NODE ->"; echo "$listed" | sed 's/^/    /'
grep -q "$PARAM" <<<"$listed" || fail "$PARAM not in 'ros2 param list $PARAMS_NODE'"

got="$(timeout 12 ros2 param get "$PARAMS_NODE" "$PARAM" 2>/dev/null)"
log "ros2 param get $PARAMS_NODE $PARAM -> $got"
grep -q "$PARAM_INIT" <<<"$got" || fail "initial $PARAM expected $PARAM_INIT, got: $got"

set_out="$(timeout 12 ros2 param set "$PARAMS_NODE" "$PARAM" "$PARAM_NEW" 2>&1)"
log "ros2 param set $PARAMS_NODE $PARAM $PARAM_NEW -> $set_out"
grep -qi "successful" <<<"$set_out" || fail "set $PARAM=$PARAM_NEW not successful: $set_out"

got2="$(timeout 12 ros2 param get "$PARAMS_NODE" "$PARAM" 2>/dev/null)"
log "ros2 param get (after set) -> $got2"
grep -q "$PARAM_NEW" <<<"$got2" || fail "after set, $PARAM expected $PARAM_NEW, got: $got2"

# Out-of-range set must be rejected (range -50..50); the CLI prints the failure
# to stderr, so capture 2>&1.
bad_out="$(timeout 12 ros2 param set "$PARAMS_NODE" "$PARAM" "$PARAM_BAD" 2>&1)"
log "ros2 param set $PARAMS_NODE $PARAM $PARAM_BAD (out of range) -> $bad_out"
grep -qi "successful" <<<"$bad_out" && fail "out-of-range set $PARAM=$PARAM_BAD was NOT rejected"
grep -qi "fail\|range" <<<"$bad_out" || fail "out-of-range set gave no rejection reason: $bad_out"
got3="$(timeout 12 ros2 param get "$PARAMS_NODE" "$PARAM" 2>/dev/null)"
grep -q "$PARAM_NEW" <<<"$got3" || fail "after rejected set, $PARAM should still be $PARAM_NEW, got: $got3"
log "GATE 3 ok: param list/get/set + out-of-range reject round-trip over raw zenoh"

# ---------------------------------------------------------------------------
# 4) SERVICE -- call the REAL pi_runtime capture service (std_srvs/srv/SetBool)
#    and assert success:true. This exercises the production request/response
#    path over CDR. MUST run before the Image gate (capture publishes a frame).
# ---------------------------------------------------------------------------
svc_out=""
for i in $(seq 1 15); do
  svc_out="$(timeout 15 ros2 service call "$CAPTURE_SERVICE" std_srvs/srv/SetBool "{data: true}" 2>/dev/null)"
  grep -q "success=True" <<<"$svc_out" && break
  sleep 2
done
log "ros2 service call $CAPTURE_SERVICE std_srvs/srv/SetBool {data: true} ->"
echo "$svc_out" | sed 's/^/    /'
grep -q "success=True" <<<"$svc_out" || fail "capture service did not return success=True: $svc_out"
# The response `message` field is JSON metadata; assert the documented keys are
# present (camera_id + request_id), proving the real capture-accept payload.
grep -q "camera_id" <<<"$svc_out"  || fail "SetBool response message missing 'camera_id' key: $svc_out"
grep -q "request_id" <<<"$svc_out" || fail "SetBool response message missing 'request_id' key: $svc_out"
log "GATE 4 ok: REAL pi_runtime SetBool capture service returned success + JSON keys (camera_id, request_id)"

# A background capture loop: the native + gateway Images are one-shot VOLATILE
# per capture, so a fresh frame must land WHILE the raw subscriber/echo is alive.
# Drive repeated captures (~every 2s) for the duration of the Image gates.
start_capture_loop() {
  local logf; logf="$(mktemp)"
  ( fails=0
    for _ in $(seq 1 90); do
      if ! timeout 12 ros2 service call "$CAPTURE_SERVICE" \
             std_srvs/srv/SetBool "{data: true}" >>"$logf" 2>&1; then
        fails=$((fails + 1))
      fi
      sleep 2
    done
    # Leave a breadcrumb so a timed-out Image gate is debuggable: if every (or
    # any) capture call failed, the Image gate's "no message in 90s" is a
    # downstream symptom, not the root cause. Surface the last output instead of
    # discarding it (the rest of this script echoes service-call output too).
    if [ "$fails" -gt 0 ]; then
      echo "[verify] capture-loop: $fails capture call(s) failed; last output:" >&2
      tail -n 20 "$logf" | sed 's/^/    /' >&2
    fi
    rm -f "$logf" ) &
  echo $!
}

# ---------------------------------------------------------------------------
# 5) NATIVE IMAGE TOPIC (byte-level CDR) -- the capture above publishes a native
#    sensor_msgs/msg/Image produced by zenoh_ros2_sdk. Assert the EXACT CDR wire
#    bytes via rclpy raw=True (cdr_assert.py --image): width 640 / height 480 /
#    encoding rgb8 / step 1920 / data == step*height. This proves a real
#    rclpy/rmw_zenoh_cpp client decodes precisely what the SDK serialized -- far
#    stronger than the previous `grep encoding: rgb8` semantic check.
# ---------------------------------------------------------------------------
cap_pid="$(start_capture_loop)"
log "asserting native Image byte-level CDR on $IMAGE_TOPIC (cdr_assert.py --image) ..."
if IMAGE_TOPIC="$IMAGE_TOPIC" IMAGE_W="$IMAGE_W" IMAGE_H="$IMAGE_H" IMAGE_STEP="$IMAGE_STEP" \
     python3 /cdr_assert.py --image; then
  kill "$cap_pid" 2>/dev/null; wait "$cap_pid" 2>/dev/null
  log "GATE 5 ok: native sensor_msgs/msg/Image byte-level CDR (${IMAGE_W}x${IMAGE_H} rgb8 step ${IMAGE_STEP})"
else
  rc=$?
  kill "$cap_pid" 2>/dev/null; wait "$cap_pid" 2>/dev/null
  if [ "$STRICT_IMAGE" = "1" ]; then
    fail "native Image byte-level CDR assertion failed on $IMAGE_TOPIC (see [cdr] lines)"
  else
    log "GATE 5 advisory (STRICT_IMAGE=0): native Image CDR assert rc=$rc; continuing"
  fi
fi

# ---------------------------------------------------------------------------
# 6) ROS2_GATEWAY RELAY -- the colcon-built gateway_node subscribes to dslr's raw
#    Zenoh frame blobs and republishes native sensor_msgs/msg/Image +
#    CompressedImage on the `gw/` topics. Verify (a) the node appears in the graph,
#    (b) each of its FOUR declared params round-trips via `ros2 param get/set`, and
#    (c) its republished Image topic echoes a 640x480 rgb8 frame (step 1920).
#
#    NOTE: the gateway re-reads camera_id/frame_key_prefix only at construction, so
#    a `set` updates the param STORE (what we assert) without re-wiring the live
#    subscription -- we assert the param round-trip, not a behavior change.
# ---------------------------------------------------------------------------
gw_nodes=""
for i in $(seq 1 "$DISCOVERY_TRIES"); do
  gw_nodes="$(ros2 node list 2>/dev/null)"
  grep -qx "$GATEWAY_NODE" <<<"$gw_nodes" && break
  sleep 2
done
grep -qx "$GATEWAY_NODE" <<<"$gw_nodes" || fail "gateway node $GATEWAY_NODE not in 'ros2 node list' (relay down?)"
log "gateway node $GATEWAY_NODE present in graph"

# Param round-trip on each of the four declared string params. New values are
# benign relabelings; we assert get-after-set reflects the change.
gw_param_roundtrip() {
  local name="$1" newval="$2"
  local before after set_out
  before="$(timeout 12 ros2 param get "$GATEWAY_NODE" "$name" 2>/dev/null)"
  log "ros2 param get $GATEWAY_NODE $name -> $before"
  grep -q "not set\|does not exist" <<<"$before" && fail "gateway param $name not declared: $before"
  set_out="$(timeout 12 ros2 param set "$GATEWAY_NODE" "$name" "$newval" 2>&1)"
  log "ros2 param set $GATEWAY_NODE $name $newval -> $set_out"
  grep -qi "successful" <<<"$set_out" || fail "gateway set $name=$newval not successful: $set_out"
  after="$(timeout 12 ros2 param get "$GATEWAY_NODE" "$name" 2>/dev/null)"
  log "ros2 param get (after set) $name -> $after"
  grep -q "$newval" <<<"$after" || fail "gateway param $name after set expected $newval, got: $after"
}

gw_param_roundtrip camera_id ci_cam_relabel
gw_param_roundtrip frame_key_prefix dslr/ci_cam/frames_relabel
gw_param_roundtrip image_topic /dslr/ci_cam/gw/image_raw_relabel
gw_param_roundtrip compressed_topic /dslr/ci_cam/gw/image_compressed_relabel
log "gateway param get/set round-trip ok on all four declared params"

# Republished Image topic echo: drive captures so a fresh blob is relayed while
# we echo the gateway's republished topic.
cap_pid="$(start_capture_loop)"
gw_img=""
for i in $(seq 1 30); do
  gw_img="$(timeout 12 ros2 topic echo --once --no-arr "$GATEWAY_IMAGE_TOPIC" sensor_msgs/msg/Image 2>/dev/null)"
  grep -q "encoding: rgb8" <<<"$gw_img" && break
  sleep 1
done
kill "$cap_pid" 2>/dev/null; wait "$cap_pid" 2>/dev/null
log "ros2 topic echo --once --no-arr $GATEWAY_IMAGE_TOPIC ->"; echo "$gw_img" | sed 's/^/    /'
grep -q "encoding: rgb8" <<<"$gw_img"     || fail "no republished Image with encoding rgb8 on $GATEWAY_IMAGE_TOPIC"
grep -q "width: $IMAGE_W" <<<"$gw_img"     || fail "republished Image width != $IMAGE_W on $GATEWAY_IMAGE_TOPIC"
grep -q "height: $IMAGE_H" <<<"$gw_img"    || fail "republished Image height != $IMAGE_H on $GATEWAY_IMAGE_TOPIC"
grep -q "step: $IMAGE_STEP" <<<"$gw_img"   || fail "republished Image step != $IMAGE_STEP on $GATEWAY_IMAGE_TOPIC"
log "GATE 6 ok: ros2_gateway params round-trip + republished Image (${IMAGE_W}x${IMAGE_H} rgb8 step ${IMAGE_STEP})"

echo
echo "::::: ALL INTEGRATION GATES PASSED :::::"
log "real pi_runtime daemon + ros2_gateway relay are full ROS 2 citizens down to the CDR bytes"
exit 0
