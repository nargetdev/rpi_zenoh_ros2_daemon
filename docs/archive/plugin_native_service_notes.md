> Historical — superseded by the native rmw_zenoh path (Track B). Kept for reference only.

# Plugin-Native ROS 2 Service Notes

This note captures the next step if we want the Raspberry Pi queryable to appear directly as a ROS 2 service server through `zenoh-plugin-ros2dds`, without the ROS 2 gateway acting as the service adapter.

## What the Current Bridge Expects

The current `zenoh-plugin-ros2dds` source shows the following behavior:

### Service Name to Zenoh Key

`ros2_name_to_key_expr()` strips the leading `/` from the ROS name and prefixes the configured namespace if one is set.

That means a ROS 2 service such as:

```text
/dslr/capture
```

maps to a Zenoh key such as:

```text
dslr/capture
```

or:

```text
robot1/dslr/capture
```

if the bridge namespace is `/robot1`.

### Request Path

The bridge code for `route_service_cli.rs` shows:

- DDS requests arrive as:
  - 4-byte CDR header
  - 16-byte request correlation header
  - serialized ROS request body
- when bridged to Zenoh:
  - the 16-byte request correlation header is removed from the payload
  - that correlation header is moved into the Zenoh attachment
  - the query payload becomes:
    - 4-byte CDR header
    - serialized ROS request body

### Reply Path

The bridge expects the Zenoh reply payload to contain:

- 4-byte CDR header
- serialized ROS response body

The bridge then reinserts the 16-byte request correlation header before writing the DDS reply.

### Discovery

The ROS 2 bridge also manages liveliness and DDS discovery state around service client/server routes. That means a fully native Pi-side service implementation needs to be compatible at both:

- payload framing level
- discovery and route announcement level

## What This Means Practically

To make the Pi runtime act as a direct ROS 2 service server through the plugin, it needs to do all of the following:

1. Serve the exact Zenoh service key expected by the plugin.
2. Parse a CDR-encoded ROS service request payload.
3. Read the request correlation header from the Zenoh attachment.
4. Serialize the ROS service response body back into CDR.
5. Reply with the exact payload shape the bridge expects.

## Recommended Phase 2 Plan

1. Pick a minimal ROS 2 service type, ideally a custom service with only strings and booleans.
2. Generate an IDL for that service and lock the exact request/response wire layout.
3. Implement a tiny serializer/deserializer on the Pi side.
4. Stand up a Zenoh queryable on the Pi that speaks that exact payload shape.
5. Validate with `ros2 service call` from the mothership before mixing in image publication.

## Why the Current Repo Starts With an Adapter

The current scaffold keeps the hard part isolated:

- the Pi already owns capture and raw image publication
- the mothership already owns ROS 2 service exposure and ROS topic publication

That gives us an end-to-end path we can run quickly, while leaving the direct plugin-native service server as a focused compatibility increment instead of mixing both problems at once.
