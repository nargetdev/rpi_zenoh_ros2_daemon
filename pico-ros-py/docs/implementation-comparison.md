# rmw_zenoh client implementations — comparison

Four ways to be a first-class ROS 2 participant over Zenoh **without a ROS 2
install**, all interoperable on the same `rmw_zenoh` graph. This frames where
`pico-ros-py` sits and what we can borrow.

| | **Pico-ROS** | **zenoh_ros2_sdk** | **pico-ros-py** (this) | **oxidros-zenoh** |
|---|---|---|---|---|
| Language / runtime | C, `zenoh-pico` | Python, `eclipse-zenoh` | Python (wraps the SDK) | Rust, `zenoh` + tokio |
| Target device | MCU / bare metal | Linux host | Linux host (Raspberry Pi) | Linux host |
| Transport approach | **clean-room** rmw_zenoh in C | clean-room on eclipse-zenoh | **wraps** zenoh_ros2_sdk | **clean-room** rmw_zenoh in Rust |
| CDR serdes | hand-rolled (Micro-CDR) | `rosbags` typestore | via the SDK (`rosbags`) | own derive (`ros2-types-derive`) |
| Type source | generated `user_types.h` | git-cloned `.msg` repos | git-cloned (via SDK) | compiled `oxidros-msg` crates |
| Pub / Sub | ✅ | ✅ | ✅ | ✅ (+ QoS) |
| Services (cli/srv) | ✅ | ✅ | ✅ | ✅ |
| **Parameter server** | ✅ `picoparams` (6 srv) | ❌ (the gap) | ✅ (6 srv + events) | ✅ (6 srv, full) |
| Graph / discovery | liveliness tokens | liveliness tokens | via SDK tokens | ✅ `graph_cache` (full) |
| `get_type_description` | — | — | — | ✅ `type_description.rs` |
| QoS profiles | basic | encoded tokens | via SDK | ✅ `qos.rs` profiles |
| CLI args / param files | — | — | — | ✅ loads `--ros-args -p`, param files |
| Concurrency model | single/loop | threads + callbacks | threads + callbacks | async (`tokio::select!`) |
| License | BSD-3 | Apache-2.0 | Apache-2.0 | Apache-2.0 |
| Maturity for params | reference | n/a | new, harness-validated | most complete |

## What oxidros-zenoh adds to the picture

oxidros is a `safe_drive` fork; `oxidros-zenoh` is its Zenoh-native backend. It
is the **Rust analogue of Pico-ROS** — clean-room rmw_zenoh, not a wrapper — but
full-featured on a Linux host. Its parameter server (`src/parameter.rs`,
`oxidros-core::parameter::{Parameters, Value}`) is the most complete of the four
and is worth mining for `pico-ros-py`:

- **Same 6 services, same `~/` private names** as our implementation —
  `~/list_parameters`, `~/get_parameters`, `~/set_parameters`,
  `~/set_parameters_atomically`, `~/describe_parameters`,
  `~/get_parameter_types`. This independently corroborates our service set.
- **Initial parameters from ROS 2 args + param files** — it reads
  `--ros-args -p name:=value` and per-node/FQN parameter rules at startup.
  `pico-ros-py` currently only declares params in code; this is the obvious next
  feature (an `argv`/YAML loader feeding `DictParameterBackend`).
- **Event-loop model** (`process_once`, `wait`, `try_process_once`,
  `take_updated`) rather than callbacks — the app pulls "which params changed"
  off a set. A nice alternative ergonomic to our `on_set` hook.
- **`get_type_description` service** and a real **graph cache** — neither the SDK
  nor pico-ros-py implements these; relevant if we want `ros2 node info` /
  type-description round-trips to work fully.
- **Real integration tests** (`tests/parameters.rs`) against a router — the same
  shape as our hermetic Docker harness, just in-process Rust.

## Takeaways for pico-ros-py

1. **Service set is confirmed** — three independent implementations agree on the
   six `rcl_interfaces` services + `~/` naming.
2. **Borrow next:** a `--ros-args -p` / YAML **parameter loader** (oxidros has the
   cleanest model), and optionally a `take_updated()`-style change set alongside
   `on_set`.
3. **Later, if needed:** `get_type_description` and a fuller graph cache — both
   present in oxidros, absent in our SDK base.
4. **Positioning:** pico-ros-py is the only *wrapper* of the four (stands on the
   SDK instead of reimplementing the wire). That is its reason to exist (least
   code, Python-native), and the reason it inherits the SDK's gaps — which is why
   borrowing oxidros's param ergonomics, not its transport, is the right move.
