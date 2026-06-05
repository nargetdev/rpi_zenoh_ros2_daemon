# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 the pico-ros-py authors
#
# A Python re-imagining of Pico-ROS `picoros` (BSD-3-Clause, Ubiquity Robotics).
# Same surface -- Interface, Node, Publisher, Subscriber, Service server/client
# -- but implemented on top of `zenoh_ros2_sdk` instead of zenoh-pico, so it
# runs on hosts like the Raspberry Pi without a ROS 2 install.
"""Pico-ROS-style node/pub/sub/service API for Python runtimes."""

from __future__ import annotations

import argparse
import contextlib
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Optional

# Serializes node identity pinning (see _pinned_node_id) across Node creation.
_IDENTITY_LOCK = threading.Lock()


def parse_locator(locator: str) -> tuple[str, int]:
    """Parse a Pico-ROS-style locator like ``tcp/127.0.0.1:7447``.

    Also accepts a bare ``host:port`` or ``host`` (defaulting to port 7447).
    """
    text = locator.strip()
    if "/" in text:
        # drop the protocol prefix ("tcp/", "udp/", ...)
        text = text.split("/", 1)[1]
    host, _, port = text.partition(":")
    return host or "127.0.0.1", int(port) if port else 7447


@dataclass
class Interface:
    """Network interface config (mirrors Pico-ROS ``picoros_interface_t``)."""

    mode: str = "client"
    locator: str = "tcp/127.0.0.1:7447"
    domain_id: int = 0

    @property
    def router_ip(self) -> str:
        return parse_locator(self.locator)[0]

    @property
    def router_port(self) -> int:
        return parse_locator(self.locator)[1]

    @classmethod
    def from_args(cls, argv: Optional[list[str]] = None) -> "Interface":
        """Parse ``-m/--mode`` and ``-a/--locator`` like the Pico-ROS examples."""
        parser = argparse.ArgumentParser(add_help=True)
        parser.add_argument("-m", "--mode", default="client")
        parser.add_argument(
            "-a", "--locator", "--address", default="tcp/127.0.0.1:7447"
        )
        parser.add_argument("-d", "--domain", type=int, default=0)
        args, _ = parser.parse_known_args(argv)
        return cls(mode=args.mode, locator=args.locator, domain_id=args.domain)


@contextlib.contextmanager
def _pinned_node_id(session: Any, node_id: int) -> Iterator[None]:
    """Force the SDK to reuse one node_id for every entity created inside.

    The SDK allocates a fresh node_id per publisher/subscriber/service, so a
    set of endpoints that should be *one* ROS node would otherwise show up as
    several. Pinning the allocator while a Node declares its endpoints makes
    them share a single graph identity -- which is also what makes the six
    parameter services resolve as one node under `ros2 param`.
    """
    original = session.get_next_node_id
    session.get_next_node_id = lambda: node_id
    try:
        yield
    finally:
        session.get_next_node_id = original


class Node:
    """A ROS 2 node (mirrors Pico-ROS ``picoros_node_t``).

    All endpoints created through a Node share its name, namespace, domain, and
    a single graph node identity.
    """

    def __init__(
        self,
        name: str,
        interface: Optional[Interface] = None,
        *,
        namespace: str = "/",
        domain_id: Optional[int] = None,
        router_ip: Optional[str] = None,
        router_port: Optional[int] = None,
    ) -> None:
        iface = interface or Interface()
        self.name = name
        self.namespace = namespace if namespace.startswith("/") else "/" + namespace
        self.domain_id = domain_id if domain_id is not None else iface.domain_id
        self.router_ip = router_ip if router_ip is not None else iface.router_ip
        self.router_port = router_port if router_port is not None else iface.router_port

        from zenoh_ros2_sdk import ZenohSession  # lazy: keep import optional

        self._session = ZenohSession.get_instance(self.router_ip, self.router_port)
        # One node_id for the whole node (see _pinned_node_id).
        self._node_id = self._session.get_next_node_id()
        self._entities: list[Any] = []

    @property
    def fully_qualified_name(self) -> str:
        if self.namespace == "/":
            return "/" + self.name
        return f"{self.namespace}/{self.name}"

    def resolve_name(self, name: str) -> str:
        """Resolve a relative name against this node (``~`` semantics)."""
        if name.startswith("/"):
            return name
        return f"{self.fully_qualified_name}/{name}"

    # -- entity factories --------------------------------------------------
    def create_publisher(
        self,
        topic: str,
        msg_type: str,
        *,
        msg_definition: Optional[str] = None,
        qos: Optional[object] = None,
    ) -> "Publisher":
        from zenoh_ros2_sdk import ROS2Publisher

        with _IDENTITY_LOCK, _pinned_node_id(self._session, self._node_id):
            impl = ROS2Publisher(
                topic=topic,
                msg_type=msg_type,
                msg_definition=msg_definition,
                node_name=self.name,
                namespace=self.namespace,
                domain_id=self.domain_id,
                router_ip=self.router_ip,
                router_port=self.router_port,
                qos=qos,
            )
        pub = Publisher(impl)
        self._entities.append(pub)
        return pub

    def create_subscription(
        self,
        topic: str,
        msg_type: str,
        callback: Callable[[Any], None],
        *,
        msg_definition: Optional[str] = None,
        qos: Optional[object] = None,
    ) -> "Subscription":
        from zenoh_ros2_sdk import ROS2Subscriber

        with _IDENTITY_LOCK, _pinned_node_id(self._session, self._node_id):
            impl = ROS2Subscriber(
                topic=topic,
                msg_type=msg_type,
                callback=callback,
                msg_definition=msg_definition,
                node_name=self.name,
                namespace=self.namespace,
                domain_id=self.domain_id,
                router_ip=self.router_ip,
                router_port=self.router_port,
                qos=qos,
            )
        sub = Subscription(impl)
        self._entities.append(sub)
        return sub

    def create_service(
        self,
        service_name: str,
        srv_type: str,
        callback: Callable[[Any], Any],
        *,
        mode: str = "callback",
    ) -> "ServiceServer":
        from zenoh_ros2_sdk import ROS2ServiceServer

        with _IDENTITY_LOCK, _pinned_node_id(self._session, self._node_id):
            impl = ROS2ServiceServer(
                service_name=service_name,
                srv_type=srv_type,
                callback=callback,
                node_name=self.name,
                namespace=self.namespace,
                domain_id=self.domain_id,
                router_ip=self.router_ip,
                router_port=self.router_port,
                mode=mode,
            )
        _repair_service_types(impl)
        srv = ServiceServer(impl)
        self._entities.append(srv)
        return srv

    def create_client(
        self,
        service_name: str,
        srv_type: str,
        *,
        timeout: float = 10.0,
    ) -> "ServiceClient":
        from zenoh_ros2_sdk import ROS2ServiceClient

        with _IDENTITY_LOCK, _pinned_node_id(self._session, self._node_id):
            impl = ROS2ServiceClient(
                service_name=service_name,
                srv_type=srv_type,
                node_name=self.name,
                namespace=self.namespace,
                domain_id=self.domain_id,
                router_ip=self.router_ip,
                router_port=self.router_port,
                timeout=timeout,
            )
        _repair_service_types(impl)
        client = ServiceClient(impl)
        self._entities.append(client)
        return client

    def close(self) -> None:
        for entity in reversed(self._entities):
            with contextlib.suppress(Exception):
                entity.close()
        self._entities.clear()

    def __enter__(self) -> "Node":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def _repair_service_types(impl: Any) -> None:
    """Register nested message types the SDK left undefined for a service.

    See pico_ros_py.picoserdes.ensure_nested_types. Applied to both server and
    client so a service whose Request/Response carries nested messages (e.g. the
    rcl_interfaces parameter services) can (de)serialize.
    """
    from .picoserdes import ensure_nested_types

    session = impl.session_mgr
    for store_type in (
        getattr(impl, "request_store_type", None),
        getattr(impl, "response_store_type", None),
    ):
        if store_type:
            ensure_nested_types(session, store_type)


# ---------------------------------------------------------------------------
# Thin endpoint wrappers -- give the SDK objects a small, Pico-ROS-ish surface
# and a uniform close().
# ---------------------------------------------------------------------------
class Publisher:
    def __init__(self, impl: Any) -> None:
        self._impl = impl

    def publish(self, *args: Any, **fields: Any) -> None:
        if args:
            if len(args) != 1 or not isinstance(args[0], dict):
                raise TypeError("publish() takes message fields as kwargs or a single dict")
            fields = {**args[0], **fields}
        self._impl.publish(**fields)

    @property
    def topic(self) -> str:
        return self._impl.topic

    def close(self) -> None:
        self._impl.close()


class Subscription:
    def __init__(self, impl: Any) -> None:
        self._impl = impl

    @property
    def topic(self) -> str:
        return self._impl.topic

    def close(self) -> None:
        self._impl.close()


class ServiceServer:
    def __init__(self, impl: Any) -> None:
        self._impl = impl

    @property
    def response_class(self) -> Any:
        return self._impl.response_msg_class

    @property
    def request_class(self) -> Any:
        return self._impl.request_msg_class

    def take_request(self, timeout: Optional[float] = None) -> Any:
        return self._impl.take_request(timeout=timeout)

    def send_response(self, key: Any, response: Any) -> None:
        self._impl.send_response(key, response)

    def close(self) -> None:
        self._impl.close()


class ServiceClient:
    def __init__(self, impl: Any) -> None:
        self._impl = impl

    def call(self, **fields: Any) -> Any:
        return self._impl.call(**fields)

    def call_async(self, callback: Callable[[Any], None], **fields: Any) -> None:
        self._impl.call_async(callback, **fields)

    def close(self) -> None:
        self._impl.close()


def spin(*nodes: Node, period: float = 0.1) -> None:
    """Block until Ctrl-C, then close the given nodes (mirrors the Pico-ROS
    ``while(picoros_keep_running)`` example loop)."""
    try:
        while True:
            time.sleep(period)
    except KeyboardInterrupt:
        pass
    finally:
        for node in nodes:
            with contextlib.suppress(Exception):
                node.close()
