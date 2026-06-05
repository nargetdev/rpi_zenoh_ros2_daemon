"""Hermetic unit tests for the colorbars spike overlay helpers.

These tests do not import ``zenoh_ros2_sdk`` at module load — the helpers
under test are SDK-free pure-Python functions — so no fake-SDK monkeypatch
fixture is needed. They guard the two non-obvious invariants that the
live-router round-trip can't quickly tell us:

  1. ``_epoch_lines`` decomposes an integer nanoseconds-since-epoch into the
     expected 7-row block with the input ``ns`` value preserved bit-for-bit.
  2. ``_render_frame`` returns a contiguous ``uint8`` array of the right size,
     and the overlay actually writes pixels (top-left region differs from a
     no-overlay render of the same instant).
"""
from __future__ import annotations

import numpy as np

from spikes.colorbars_cdr_publisher import _epoch_lines, _load_font, _render_frame


def test_epoch_lines_match_input_ns():
    t_ns = 1_780_617_095_953_336_789
    lines = _epoch_lines(t_ns)
    assert len(lines) == 7
    labels = [line.split(":", 1)[0].strip() for line in lines]
    assert labels == ["DAYS", "HOURS", "MIN", "SEC", "ms", "us", "ns"]
    assert lines[6].rstrip().endswith(str(t_ns))
    assert lines[3].rstrip().endswith(str(t_ns // 1_000_000_000))


def test_render_frame_returns_uint8_array_of_correct_size():
    width, height = 160, 120
    t_ns = 1_780_617_095_953_336_000
    font = _load_font(14)

    with_overlay = _render_frame(width, height, t_ns, font, overlay=True)
    without_overlay = _render_frame(width, height, t_ns, font, overlay=False)

    assert with_overlay.dtype == np.uint8
    assert with_overlay.size == width * height * 3
    assert without_overlay.size == width * height * 3
    # Overlay panel sits at (~8, ~8); the first byte at (0,0) is the white
    # colorbar in both renders, so compare a region the overlay actually
    # covers — pixel (20, 20).
    px_index = (20 * width + 20) * 3
    assert (
        with_overlay[px_index:px_index + 3].tolist()
        != without_overlay[px_index:px_index + 3].tolist()
    ), "overlay rendering did not write pixels in the panel region"
