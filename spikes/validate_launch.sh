#!/usr/bin/env bash
# Plain-tmux launcher for the colorbars validation session.
# (tmuxp 1.55 / libtmux 0.46 has a new_session regression on this Pi's tmux
# 3.5a, so we build the layout described in validate.tmuxp.yaml directly.)
#   ./spikes/validate_launch.sh   then:  tmux attach -t pgwaam-colorbars-validate
set -uo pipefail
S=pgwaam-colorbars-validate
REPO=/home/notbroken/rpi_zenoh_ros2_daemon
PY=/opt/pgwaam/venv/bin/python
ROUTER=172.31.1.252:7447

tmux kill-session -t "$S" 2>/dev/null
tmux new-session -d -s "$S" -n colorbars -c "$REPO"

# pane 0 — publisher (Pi -> live router)
tmux send-keys -t "$S:colorbars.0" \
  "clear; echo '== PUBLISHER -> tcp/$ROUTER  (sensor_msgs/Image on /spike/colorbars) =='; env -u ZENOH_CONFIG_OVERRIDE -u ZENOH_SESSION_CONFIG_URI PYTHONUNBUFFERED=1 $PY spikes/colorbars_cdr_publisher.py --router-ip 172.31.1.252 --router-port 7447 --domain-id 0 --rate 2 --duration 0" C-m

# pane 1 — verifier (router -> CDR-decode Image back)
tmux split-window -h -t "$S:colorbars" -c "$REPO"
tmux send-keys -t "$S:colorbars.1" \
  "clear; echo '== VERIFIER <- router (CDR-decode) =='; sleep 3; $PY spikes/colorbars_verify_sub.py $ROUTER 0" C-m
tmux select-layout -t "$S:colorbars" even-horizontal

# window 1 — fleet heartbeats (MQTT)
tmux new-window -t "$S" -n fleet -c "$REPO"
tmux send-keys -t "$S:fleet" \
  "clear; echo '== FLEET HEARTBEATS (MQTT pgwaam/heartbeat/#) =='; $PY spikes/fleet_heartbeat_mon.py 172.31.1.252" C-m

tmux select-window -t "$S:colorbars"
echo "launched $S"
