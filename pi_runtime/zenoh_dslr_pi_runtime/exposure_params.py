"""Serve camera exposure settings as ROS 2 parameters via ``pico-ros-py``.

Exposes the gphoto2 exposure keys (``shutterspeed``, ``aperture``, ``iso``,
``autoexposuremode`` -- whatever is declared in config) on the standard ROS 2
parameter interface, so they can be driven with ``ros2 param get/set`` from any
``rmw_zenoh`` shell. The runtime reads :meth:`current` before each capture and
applies the non-empty values via ``gphoto2 --set-config``.

This keeps the capture trigger a plain ``std_srvs/srv/SetBool`` -- no custom
service interface is needed on the caller side. Parameters are persistent: a
value set once sticks until changed (or until the node restarts).
"""

from __future__ import annotations

import logging

from .models import ExposureParamsConfig

LOGGER = logging.getLogger("zenoh_dslr_pi_runtime.exposure")


class ExposureParameterServer:
    """A pico-ros-py parameter server for camera exposure settings."""

    def __init__(self, config: ExposureParamsConfig) -> None:
        self._config = config
        self._param_names = list(config.params.keys())
        self._backend = None
        self._node = None
        self._server = None

    def start(self) -> "ExposureParameterServer":
        # Lazy import: pico-ros-py is only required when exposure params are
        # enabled, so a default deployment need not install it.
        try:
            from pico_ros_py import (
                DictParameterBackend,
                Interface,
                Node,
                ParameterDescriptor,
                ParameterServer,
                ParameterType,
            )
        except ImportError as exc:  # pragma: no cover - install-time guard
            raise RuntimeError(
                "exposure params are enabled but pico-ros-py is not installed; "
                "install the runtime with the 'exposure' extra "
                "(e.g. `uv run --extra exposure ...`)"
            ) from exc

        backend = DictParameterBackend()
        for name, value in self._config.params.items():
            backend.declare(
                name,
                value,
                descriptor=ParameterDescriptor(
                    type=ParameterType.STRING,
                    description=f"gphoto2 {name} (empty = leave camera as-is)",
                    # ros2 param set infers int/double from literals like 400 or
                    # 5.6; dynamic typing lets those land without a type error.
                    dynamic_typing=True,
                ),
            )

        def _report(name, pv) -> None:
            LOGGER.info("exposure param set: %s -> %r", name, pv.value)

        backend.on_set = _report

        iface = Interface(
            mode="client",
            locator=f"tcp/{self._config.router_ip}:{self._config.router_port}",
            domain_id=self._config.domain_id,
        )
        node = Node(self._config.node_name, iface)
        server = ParameterServer(node, backend).start()

        self._backend = backend
        self._node = node
        self._server = server
        LOGGER.info(
            "exposure parameter server started: node=%s params=%s router=%s:%s",
            node.fully_qualified_name,
            self._param_names,
            self._config.router_ip,
            self._config.router_port,
        )
        return self

    def current(self) -> dict[str, str]:
        """Return the non-empty exposure settings as ``{gphoto2_key: value}``."""
        backend = self._backend
        if backend is None:
            return {}
        out: dict[str, str] = {}
        for name in self._param_names:
            try:
                raw = backend.value_of(name)
            except KeyError:  # pragma: no cover - declared names only
                continue
            if raw is None:
                continue
            text = str(raw).strip()
            if text:
                out[name] = text
        return out

    def stop(self) -> None:
        try:
            if self._server is not None:
                self._server.stop()
        finally:
            if self._node is not None:
                try:
                    self._node.close()
                except Exception:  # pragma: no cover - best-effort cleanup
                    LOGGER.debug("exposure node close failed", exc_info=True)
