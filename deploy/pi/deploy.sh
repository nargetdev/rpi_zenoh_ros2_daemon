#!/usr/bin/env bash
#
# Roll out the Zenoh DSLR Pi runtime (capture service + heartbeat/core-temp
# reporting) to every Raspberry Pi node and install it as a systemd service.
#
# Usage:
#   deploy/pi/deploy.sh                # deploy to all nodes in FLEET below
#   deploy/pi/deploy.sh id2-rpi4 pi3m50  # deploy to a subset
#
# Each fleet entry is "ssh_target=config_basename". The config is taken from
# pi_runtime/config/<config_basename> and shipped as the node's runtime config.
# Override the fleet with the FLEET env var (same "target=config" format).
set -euo pipefail

# host login target  ->  config file under pi_runtime/config/
DEFAULT_FLEET=(
  "notbroken@notbroken.local=notbroken.example.json"
  "id1-cm5@id1-cm5.local=id1-cm5.example.json"
  "id2-rpi4@id2-rpi4.local=id2-rpi4.example.json"
  "pi3m50@pi3m50.local=pi3m50.example.json"
)

INSTALL_DIR="/opt/zenoh-dslr"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UNIT_TEMPLATE="${REPO_ROOT}/deploy/pi/zenoh-dslr-runtime.service"

# Build the working fleet: explicit FLEET env, else CLI host filter, else all.
if [[ -n "${FLEET:-}" ]]; then
  read -r -a FLEET_ENTRIES <<<"${FLEET}"
else
  FLEET_ENTRIES=("${DEFAULT_FLEET[@]}")
fi

select_entries() {
  # If host names were passed as args, keep only matching fleet entries.
  [[ $# -eq 0 ]] && { printf '%s\n' "${FLEET_ENTRIES[@]}"; return; }
  local entry target
  for entry in "${FLEET_ENTRIES[@]}"; do
    target="${entry%%=*}"
    for want in "$@"; do
      if [[ "${target}" == "${want}"* || "${target%%@*}" == "${want}" ]]; then
        printf '%s\n' "${entry}"
      fi
    done
  done
}

deploy_one() {
  local target="$1" config_name="$2"
  local user="${target%%@*}"
  local config_path="${REPO_ROOT}/pi_runtime/config/${config_name}"

  if [[ ! -f "${config_path}" ]]; then
    echo "!! missing config ${config_path} for ${target}, skipping" >&2
    return 1
  fi

  echo "==> ${target}: syncing runtime to ${INSTALL_DIR}"
  ssh "${target}" "sudo mkdir -p '${INSTALL_DIR}' && sudo chown \$(id -un):\$(id -gn) '${INSTALL_DIR}'"
  rsync -az --delete \
    --exclude '__pycache__' --exclude '.venv' --exclude 'captures' \
    "${REPO_ROOT}/pi_runtime/" "${target}:${INSTALL_DIR}/pi_runtime/"
  rsync -az "${REPO_ROOT}/deploy/" "${target}:${INSTALL_DIR}/deploy/"
  rsync -az "${config_path}" "${target}:${INSTALL_DIR}/config.json"

  echo "==> ${target}: creating venv + installing package"
  ssh "${target}" "
    set -e
    command -v vcgencmd >/dev/null 2>&1 || echo '   (note: vcgencmd not found; throttled will report null)'
    python3 -m venv '${INSTALL_DIR}/venv'
    '${INSTALL_DIR}/venv/bin/pip' install --quiet --upgrade pip
    '${INSTALL_DIR}/venv/bin/pip' install --quiet '${INSTALL_DIR}/pi_runtime'
  "

  echo "==> ${target}: installing systemd unit"
  local tmp_unit
  tmp_unit="$(mktemp)"
  sed -e "s#__RUN_USER__#${user}#g" -e "s#__INSTALL_DIR__#${INSTALL_DIR}#g" "${UNIT_TEMPLATE}" >"${tmp_unit}"
  # Ship the rendered unit and env file as plain files, then move into place with sudo.
  rsync -az "${tmp_unit}" "${target}:/tmp/zenoh-dslr-runtime.service"
  rm -f "${tmp_unit}"
  ssh "${target}" "
    set -e
    printf 'RUNTIME_CONFIG=%s\n' '${INSTALL_DIR}/config.json' | sudo tee /etc/default/zenoh-dslr-runtime >/dev/null
    sudo mv /tmp/zenoh-dslr-runtime.service /etc/systemd/system/zenoh-dslr-runtime.service
    sudo systemctl daemon-reload
    sudo systemctl enable --now zenoh-dslr-runtime.service
    sudo systemctl restart zenoh-dslr-runtime.service
  "

  echo "==> ${target}: status"
  ssh "${target}" "systemctl --no-pager --lines=5 status zenoh-dslr-runtime.service || true"
  echo "==> ${target}: done"
  echo
}

mapfile -t TARGETS < <(select_entries "$@")
if [[ ${#TARGETS[@]} -eq 0 ]]; then
  echo "no matching fleet entries for: $*" >&2
  exit 1
fi

rc=0
for entry in "${TARGETS[@]}"; do
  deploy_one "${entry%%=*}" "${entry#*=}" || rc=1
done
exit "${rc}"
