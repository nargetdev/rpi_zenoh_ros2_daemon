from __future__ import annotations

import argparse

from .models import PiRuntimeSettings
from .runtime import PiDslrRuntime


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    settings = PiRuntimeSettings.from_file(args.config)
    runtime = PiDslrRuntime(settings)
    runtime.run()


if __name__ == "__main__":
    main()
