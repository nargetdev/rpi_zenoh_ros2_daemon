from __future__ import annotations

import argparse
import logging

from .models import PiRuntimeSettings
from .runtime import PiDslrRuntime
from .zenoh_native_session import force_native_client_mode

LOGGER = logging.getLogger("zenoh_dslr_pi_runtime.cli")


def main() -> None:
    # Force native ROS 2 Zenoh sessions to CLIENT mode BEFORE any session is
    # constructed (the SDK singleton caches the first opened session).
    override_str = force_native_client_mode()
    LOGGER.info("native ROS 2 Zenoh sessions forced to CLIENT mode: %s", override_str)
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    settings = PiRuntimeSettings.from_file(args.config)
    runtime = PiDslrRuntime(settings)
    runtime.run()


if __name__ == "__main__":
    main()
