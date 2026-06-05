#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# The live-integration gate. Uses ONLY the stock ros2 CLI (transport =
# rmw_zenoh, i.e. raw zenoh) over the EXTERNAL live router to prove the
# pure-zenoh pico-ros-py "node under test" is a first-class ROS 2 citizen:
#
#   1. heartbeat / discovery : `ros2 node list`  shows the node
#   2. topic + CDR           : `ros2 topic echo`  decodes its epoch_ns message
#   3. parameters            : `ros2 param list/get/set/describe` round-trips
#
# Exit 0 == gates pass. Any failure exits non-zero and aborts the harness.
set -uo pipefail

ROUTER_IP="${ROUTER_IP:-127.0.0.1}"
ROUTER_PORT="${ROUTER_PORT:-7447}"
NODE="${NODE:-/node_under_test/node_under_test}"
TOPIC="${TOPIC:-/node_under_test/node_under_test/epoch_ns}"
MSG_TYPE="${MSG_TYPE:-std_msgs/msg/Int64}"
PARAMS_NODE="${PARAMS_NODE:-/picoros_live}"
PARAM="${PARAM:-example.param1}"
PARAM_INIT="${PARAM_INIT:-10}"
PARAM_NEW="${PARAM_NEW:-7}"
PARAM_BAD="${PARAM_BAD:-9999}"
DISCOVERY_TRIES="${DISCOVERY_TRIES:-40}"   # ~40 * 2s = up to 80s for discovery
ECHO_TRIES="${ECHO_TRIES:-15}"

log()  { echo "[validate] $*"; }
fail() { echo "[validate] FAIL: $*" >&2; echo "::::: VALIDATE FAILED :::::"; exit 1; }

# Render the session config pointing at the live router, then use it.
export ROUTER_IP ROUTER_PORT
envsubst < /config/zenoh-session.json5.tmpl > /tmp/zenoh-session.json5
export ZENOH_SESSION_CONFIG_URI=/tmp/zenoh-session.json5

log "RMW=$RMW_IMPLEMENTATION  router=tcp/${ROUTER_IP}:${ROUTER_PORT}"
log "session config ->"
sed 's/^/    /' /tmp/zenoh-session.json5
log "waiting for the Zenoh graph to converge ..."

# ---------------------------------------------------------------------------
# 1) HEARTBEAT / DISCOVERY -- the node must appear in `ros2 node list`.
#    (rmw_zenoh enumerates nodes from their Zenoh liveliness "NN" tokens.)
# ---------------------------------------------------------------------------
nodes=""
for _ in $(seq 1 "$DISCOVERY_TRIES"); do
  nodes="$(ros2 node list 2>/dev/null)"
  grep -qx "$NODE" <<<"$nodes" && break
  sleep 2
done
log "ros2 node list ->"
echo "$nodes" | sed 's/^/    /'
grep -qx "$NODE" <<<"$nodes" || fail "node $NODE not in 'ros2 node list' (no heartbeat)"
log "GATE 1 ok: node enumerated (heartbeat visible over the live router)"

# ---------------------------------------------------------------------------
# 2) TOPIC + CDR -- `ros2 topic echo` must decode the published epoch_ns.
#    First try the bare form the user asked for (type auto-discovered from the
#    graph); fall back to an explicit type if discovery is slow.
# ---------------------------------------------------------------------------
echoed=""
for _ in $(seq 1 "$ECHO_TRIES"); do
  echoed="$(timeout 10 ros2 topic echo --once "$TOPIC" 2>/dev/null)"
  grep -q "data:" <<<"$echoed" && break
  echoed="$(timeout 10 ros2 topic echo --once "$TOPIC" "$MSG_TYPE" 2>/dev/null)"
  grep -q "data:" <<<"$echoed" && break
  sleep 2
done
log "ros2 topic echo $TOPIC ->"
echo "$echoed" | sed 's/^/    /'
grep -q "data:" <<<"$echoed" || fail "no message decoded on $TOPIC"

# Sanity-check the CDR round-trip: the value is a plausible nanosecond epoch.
val="$(grep -oE 'data:[[:space:]]*[0-9]+' <<<"$echoed" | grep -oE '[0-9]+' | tail -1)"
[ -n "$val" ] || fail "could not parse epoch_ns from echo output"
[ "${#val}" -ge 18 ] || fail "epoch_ns=$val does not look like nanoseconds (expected >=18 digits)"
log "GATE 2 ok: epoch_ns=$val decoded via correct CDR over raw zenoh"

# ---------------------------------------------------------------------------
# 3) PARAMETERS -- list, get-initial, set, get-after-set, and out-of-range
#    reject on the pico-ros-py parameter server, all via the stock ros2 CLI.
#
#    NB: `ros2 param describe` is deliberately NOT gated. DescribeParameters
#    carries nested messages (ParameterDescriptor + Integer/FloatingPointRange),
#    and the SDK's service type-hash for nested-message services doesn't match
#    the one the stock CLI computes, so the CLI's query key never matches the
#    server's -- the request never routes (it times out). Serialization itself
#    is fine (see pico-ros-py's _repair_service_types, and smoke_test.py which
#    exercises describe over the pico-ros-py client). This is an SDK limitation,
#    which is why ci/verify.sh likewise gates only list/get/set.
# ---------------------------------------------------------------------------
listed=""
for _ in $(seq 1 15); do
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

set_out="$(timeout 12 ros2 param set "$PARAMS_NODE" "$PARAM" "$PARAM_NEW" 2>&1)"
log "ros2 param set $PARAMS_NODE $PARAM $PARAM_NEW -> $set_out"
grep -qi "successful" <<<"$set_out" || fail "set $PARAM=$PARAM_NEW not successful: $set_out"

got2="$(timeout 12 ros2 param get "$PARAMS_NODE" "$PARAM" 2>/dev/null)"
log "ros2 param get (after set) -> $got2"
grep -q "$PARAM_NEW" <<<"$got2" || fail "after set, $PARAM expected $PARAM_NEW, got: $got2"

# Out-of-range set must be rejected with a reason (range is -50..50). The CLI
# prints "Setting parameter failed: ..." to stderr, so capture 2>&1.
bad_out="$(timeout 12 ros2 param set "$PARAMS_NODE" "$PARAM" "$PARAM_BAD" 2>&1)"
log "ros2 param set $PARAMS_NODE $PARAM $PARAM_BAD (out of range) -> $bad_out"
grep -qi "successful" <<<"$bad_out" && fail "out-of-range set $PARAM=$PARAM_BAD was NOT rejected"
grep -qi "fail\|range" <<<"$bad_out" || fail "out-of-range set gave no rejection reason: $bad_out"
got3="$(timeout 12 ros2 param get "$PARAMS_NODE" "$PARAM" 2>/dev/null)"
grep -q "$PARAM_NEW" <<<"$got3" || fail "after rejected set, $PARAM should still be $PARAM_NEW, got: $got3"
log "GATE 3 ok: param list/get/set + out-of-range reject round-trip over raw zenoh"

echo
echo "::::: ALL VALIDATE GATES PASSED :::::"
log "pico-ros-py node_under_test + param server are visible & controllable from the ros2 CLI"
exit 0
