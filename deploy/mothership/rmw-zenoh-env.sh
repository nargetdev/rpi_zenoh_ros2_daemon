export RMW_IMPLEMENTATION=rmw_zenoh_cpp
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export ZENOH_ROUTER_CONFIG_URI="${SCRIPT_DIR}/rmw-zenoh-router.json5"
