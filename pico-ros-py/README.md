# pico-ros-py

A Python re-imagining of the [Pico-ROS](https://github.com/Pico-ROS/Pico-ROS-software)
pattern, for runtimes like the Raspberry Pi.

Pico-ROS is a lightweight **C** ROS 2 client for microcontrollers, built on
`zenoh-pico` + `rmw_zenoh`. It gives an MCU a `Node`, publishers, subscribers,
service server/client, and — crucially — a **parameter server** with a small
pluggable backend, all speaking the real ROS 2 graph protocol over Zenoh.

`pico-ros-py` keeps those **semantics** but implements them in Python on top of
[`zenoh_ros2_sdk`](https://github.com/robotis-git/zenoh_ros2_sdk), so a host that
can run CPython (a Raspberry Pi, an edge gateway, a laptop) can be a first-class
ROS 2 participant **without a ROS 2 install**.

This is an independent implementation, not a line-by-line translation — no
Pico-ROS source is included. See [`NOTICE`](NOTICE) for attribution.

## Why it exists

`zenoh_ros2_sdk` already covers Pico-ROS's transport layer in Python: CDR
serialization (via `rosbags`), `rmw_zenoh`-compatible liveliness/discovery,
type hashing, and pub/sub/services. Its **one gap is the parameter server**
(`rcl_interfaces` / `ros2 param` / rqt_reconfigure). `pico-ros-py`:

1. Adds that missing **parameter server**, with the same backend-interface shape
   as Pico-ROS `picoparams` (`ref` / `get` / `type` / `set` / `describe` /
   `list` / `prefixes`).
2. Wraps the SDK in a **`Node`** abstraction that pins one graph identity, so
   all of a node's endpoints (and all six parameter services) appear as a
   **single** node in `ros2 node list` / `ros2 param`.
3. Mirrors the Pico-ROS module layout and examples so the two projects read the
   same way.

## Module map

| Pico-ROS (C) | pico-ros-py (Python) | Role |
|---|---|---|
| `picoros` | `pico_ros_py.picoros` | `Node`, `Interface`, `Publisher`, `Subscription`, `ServiceServer`, `ServiceClient`, `spin` |
| `picoserdes` | `pico_ros_py.picoserdes` | type registration / CDR access (delegates to the SDK typestore) |
| `picoparams` | `pico_ros_py.picoparams` | `ParameterType`, `ParameterDescriptor`, `ParameterValue`, `ParameterBackend`, `DictParameterBackend`, `ParameterServer` |
| — | `pico_ros_py._rcl` | builds the rosbags `rcl_interfaces` messages on the wire |

## Install

```sh
pip install -e .            # or: pip install -e '.[dev]'
```

Requires a running `rmw_zenoh` router (`ros2 run rmw_zenoh_cpp rmw_zenohd`) on
the network, same as the Pico-ROS examples.

## Quick start

Publisher:

```python
from pico_ros_py import Interface, Node

node = Node("pico_talker", Interface(locator="tcp/127.0.0.1:7447"))
pub = node.create_publisher("/chatter", "std_msgs/msg/String")
pub.publish(data="hello")
```

Parameter server (the headline feature):

```python
from pico_ros_py import Node, ParameterServer, DictParameterBackend, IntegerRange

backend = DictParameterBackend()
backend.declare("example.param1", 10, integer_range=IntegerRange(-50, 50))
backend.declare("example.param2", 1.25, description="a double")

node = Node("picoros")
ParameterServer(node, backend).start()
# Now: ros2 param list /picoros ; ros2 param set /picoros example.param1 7
```

Implement a custom backend to bind parameters straight to your app state
(the equivalent of the Pico-ROS `api_param_*` callbacks):

```python
from pico_ros_py import ParameterBackend, ParameterValue, ParameterType, ParameterDescriptor

class MyBackend(ParameterBackend):
    def ref(self, name): ...
    def get(self, handle): ...
    def type(self, handle): ...
    def describe(self, handle): ...
    def set(self, handle, value): ...        # -> (ok: bool, reason: str)
    def list(self, prefix): ...
    def prefixes(self, prefix): ...
```

## Examples

Mirrors of the Pico-ROS `examples/` (run with `-m <mode> -a <locator>`):

- `examples/talker.py` / `examples/listener.py` — pub/sub
- `examples/add_two_ints_server.py` / `examples/add_two_ints_client.py` — services
- `examples/params_server.py` — a direct port of Pico-ROS `params_server.c`

## Docker / CI

A hermetic end-to-end harness lives in [`docker/`](docker/). It runs three
**separate containers** on a private Docker network — exactly the Raspberry Pi
↔ Arch-master split over a Zenoh router, each role with its own session,
discovering each other only through the router:

```
zenohd  (router)  ◄──  params-server  (the "pi daemon": ParameterServer)
                  ◄──  validator       (the "master": drives list/get/set, gates the run)
```

Run it:

```sh
docker compose -f docker/compose.test.yml up --build \
    --abort-on-container-exit --exit-code-from validator   # exit 0 == SMOKE OK
```

`.github/workflows/ci.yml` runs two gates: the offline unit tests, then this
harness. (The workflow lives under `pico-ros-py/.github` so it travels when the
project is split into its own repo; move it to the repo-root `.github/workflows`
at that point.)

## Tests & validation status

The **pure-Python core** — the parameter type model and `DictParameterBackend`
(type/range/read-only validation, listing, prefixes) — is unit-tested and runs
without any ROS/zenoh install:

```sh
pytest          # 23 tests
```

The **transport paths** (`Node`, the `rcl_interfaces` message construction in
`_rcl.py`, the nested-type repair, and all six live parameter services) are
validated end-to-end by the hermetic Docker harness above: a real Zenoh router
between two distinct sessions exercises list → get → set → describe, including
range rejection and the `on_set` hook. The `ParameterValue` / response wire
shapes were additionally cross-checked against a live `rmw_zenoh` graph.

Not yet covered: `rqt_reconfigure` against the running node (GUI), arm64, and
real LAN latency — see the harness's realism knobs (arm64 via QEMU, `tc netem`)
if you want that fidelity.

## License

Apache-2.0 (see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE)).
