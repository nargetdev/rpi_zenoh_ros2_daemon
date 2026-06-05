#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# The CI gate. Uses ONLY the stock ros2 CLI (transport = rmw_zenoh, i.e. raw
# zenoh) to prove that the pure-zenoh pico-ros-py daemons are first-class ROS 2
# citizens:
#
#   1. heartbeat / discovery : `ros2 node list`  shows both daemon nodes
#   2. topics                : `ros2 topic echo`  receives the talker's message
#   3. parameters            : `ros2 param get|set` round-trips on the param node
#
# Exit 0 == all gates pass. Any failure exits non-zero and aborts the harness.
set -uo pipefail

TALKER_NODE="${TALKER_NODE:-/pico_talker}"
PARAMS_NODE="${PARAMS_NODE:-/picoros}"
TOPIC="${TOPIC:-/chatter}"
PARAM="${PARAM:-example.param1}"
PARAM_NEW="${PARAM_NEW:-7}"
PARAM_INIT="${PARAM_INIT:-10}"
DISCOVERY_TRIES="${DISCOVERY_TRIES:-40}"   # ~40 * 2s = up to 80s for discovery

log()  { echo "[verify] $*"; }
fail() { echo "[verify] FAIL: $*" >&2; echo "::::: VERIFY FAILED :::::"; exit 1; }

log "RMW=$RMW_IMPLEMENTATION  session_cfg=$ZENOH_SESSION_CONFIG_URI"
log "waiting for the Zenoh graph to converge ..."

# ---------------------------------------------------------------------------
# 1) HEARTBEAT / DISCOVERY -- both daemon nodes must appear in `ros2 node list`.
#    (rmw_zenoh enumerates nodes from their Zenoh liveliness "NN" tokens; that
#    liveliness token IS the node heartbeat.)
# ---------------------------------------------------------------------------
nodes=""
for i in $(seq 1 "$DISCOVERY_TRIES"); do
  nodes="$(ros2 node list 2>/dev/null)"
  if grep -qx "$TALKER_NODE" <<<"$nodes" && grep -qx "$PARAMS_NODE" <<<"$nodes"; then
    break
  fi
  sleep 2
done
log "ros2 node list ->"
echo "$nodes" | sed 's/^/    /'
grep -qx "$TALKER_NODE" <<<"$nodes" || fail "node $TALKER_NODE not in 'ros2 node list' (no heartbeat)"
grep -qx "$PARAMS_NODE" <<<"$nodes" || fail "node $PARAMS_NODE not in 'ros2 node list' (no heartbeat)"
log "GATE 1 ok: both daemon nodes enumerated (heartbeat visible)"

# ---------------------------------------------------------------------------
# 2) TOPICS -- `ros2 topic echo` must receive the talker's published message.
# ---------------------------------------------------------------------------
echoed=""
for i in $(seq 1 10); do
  echoed="$(timeout 10 ros2 topic echo --once "$TOPIC" std_msgs/msg/String 2>/dev/null)"
  grep -q "hello from pico-ros-py" <<<"$echoed" && break
  sleep 2
done
log "ros2 topic echo $TOPIC ->"
echo "$echoed" | sed 's/^/    /'
grep -q "hello from pico-ros-py" <<<"$echoed" || fail "no message echoed on $TOPIC"
log "GATE 2 ok: topic message received over raw zenoh"

# ---------------------------------------------------------------------------
# 3) PARAMETERS -- list, get initial, set, get-after-set on the param node.
# ---------------------------------------------------------------------------
listed=""
for i in $(seq 1 15); do
  listed="$(timeout 12 ros2 param list "$PARAMS_NODE" 2>/dev/null)"
  grep -q "$PARAM" <<<"$listed" && break
  sleep 2
done
log "ros2 param list $PARAMS_NODE ->"
echo "$listed" | sed 's/^/    /'
grep -q "$PARAM" <<<"$listed" || fail "$PARAM not in 'ros2 param list $PARAMS_NODE'"

got="$(timeout 12 ros2 param get "$PARAMS_NODE" "$PARAM" 2>/dev/null)"
log "ros2 param get $PARAMS_NODE $PARAM -> $got"
grep -q "$PARAM_INIT" <<<"$got" || fail "initial $PARAM expected $PARAM_INIT, got: $got"

set_out="$(timeout 12 ros2 param set "$PARAMS_NODE" "$PARAM" "$PARAM_NEW" 2>/dev/null)"
log "ros2 param set $PARAMS_NODE $PARAM $PARAM_NEW -> $set_out"
grep -qi "successful" <<<"$set_out" || fail "set $PARAM=$PARAM_NEW not successful: $set_out"

got2="$(timeout 12 ros2 param get "$PARAMS_NODE" "$PARAM" 2>/dev/null)"
log "ros2 param get (after set) -> $got2"
grep -q "$PARAM_NEW" <<<"$got2" || fail "after set, $PARAM expected $PARAM_NEW, got: $got2"
log "GATE 3 ok: param get/set round-trip over raw zenoh"

echo
echo "::::: ALL VERIFY GATES PASSED :::::"
log "pure-zenoh pico-ros-py daemons are visible & controllable from the ros2 CLI"
exit 0
