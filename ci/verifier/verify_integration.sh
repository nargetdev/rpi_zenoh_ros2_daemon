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
#   4 service      : `ros2 service call` on the REAL std_srvs/srv/SetBool capture
#   5 image topic  : native sensor_msgs/msg/Image arrives (semantic; capture-fed)
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
log "GATE 4 ok: REAL pi_runtime SetBool capture service returned success"

# ---------------------------------------------------------------------------
# 5) NATIVE IMAGE TOPIC (semantic) -- the capture above publishes a native
#    sensor_msgs/msg/Image; assert it arrives with encoding rgb8. Large/variable
#    payload, so validated semantically (type + arrival + encoding), not byte-wise.
#
#    The Image is published ONE-SHOT per capture with VOLATILE durability, so a
#    late-joining subscriber gets nothing -- `ros2 topic echo` MUST already be
#    subscribed when a frame is published. We therefore drive captures from a
#    BACKGROUND loop (every ~2s) so a fresh frame reliably lands inside the echo
#    subscription window, rather than firing the capture only after echo gives up.
# ---------------------------------------------------------------------------
( for _ in $(seq 1 40); do
    timeout 12 ros2 service call "$CAPTURE_SERVICE" std_srvs/srv/SetBool "{data: true}" >/dev/null 2>&1
    sleep 2
  done ) &
cap_pid=$!
img=""
for i in $(seq 1 15); do
  img="$(timeout 12 ros2 topic echo --once --no-arr "$IMAGE_TOPIC" sensor_msgs/msg/Image 2>/dev/null)"
  grep -q "encoding: rgb8" <<<"$img" && break
  sleep 1
done
kill "$cap_pid" 2>/dev/null; wait "$cap_pid" 2>/dev/null
log "ros2 topic echo --once --no-arr $IMAGE_TOPIC ->"; echo "$img" | sed 's/^/    /'
if grep -q "encoding: rgb8" <<<"$img"; then
  log "GATE 5 ok: native sensor_msgs/msg/Image received with encoding rgb8"
elif [ "$STRICT_IMAGE" = "1" ]; then
  fail "no sensor_msgs/msg/Image with encoding rgb8 on $IMAGE_TOPIC"
else
  log "GATE 5 advisory (STRICT_IMAGE=0): no Image frame seen; continuing"
fi

echo
echo "::::: ALL INTEGRATION GATES PASSED :::::"
log "real pi_runtime daemon (hardware mocked) is a full ROS 2 citizen down to the CDR bytes"
exit 0
