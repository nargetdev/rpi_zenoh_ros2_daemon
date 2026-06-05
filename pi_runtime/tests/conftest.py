"""Test bootstrap: expose the repo-root ``spikes/`` package to pytest.

The ``spikes/`` directory is a standalone-script collection, not a package
under ``pi_runtime/``. Tests that exercise the spike helpers need its parent
on ``sys.path`` so ``from spikes.<module> import ...`` resolves. Mirrors the
sys-path trick used in ``spikes/dslr_image_publish_example.py``.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
