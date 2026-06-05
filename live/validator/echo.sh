#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# The live-integration gate. Uses ONLY the stock ros2 CLI (transport =
# rmw_zenoh, i.e. raw zenoh) over the EXTERNAL live router to prove the
# pure-zenoh pico-ros-py "node under test" is a first-class ROS 2 citizen:
#
#   1. heartbeat / discovery : `ros2 node list`  shows the node
#   2. topic + CDR           : `ros2 topic echo`  decodes its epoch_ns message
#
# Exit 0 == gates pass. Any failure exits non-zero and aborts the harness.
set -uo pipefail

ROUTER_IP="${ROUTER_IP:-127.0.0.1}"
ROUTER_PORT="${ROUTER_PORT:-7447}"
NODE="${NODE:-/node_under_test/node_under_test}"
TOPIC="${TOPIC:-/node_under_test/node_under_test/epoch_ns}"
MSG_TYPE="${MSG_TYPE:-std_msgs/msg/Int64}"
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

echo
echo "::::: ALL VALIDATE GATES PASSED :::::"
log "pico-ros-py node_under_test is visible & CDR-readable from the ros2 CLI"
exit 0
