# Nova Developer Guide

Documentation and examples for connecting to the Nova launch monitor by Open Launch.

## Local APIs

Nova exposes two local network APIs for receiving shot data:

| API | Protocol | Format | Use Case |
|-----|----------|--------|----------|
| OpenAPI | TCP socket | JSON | Golf simulator software integration, Custom applications |
| WebSocket | WebSocket | JSON | Custom applications, web clients |

Both APIs are receive-only. Clients connect and receive shot data as it occurs.

## Discovery

Nova advertises its services on the local network using mDNS:

| Service | mDNS Type |
|---------|-----------|
| OpenAPI | `_openapi-nova._tcp.local.` |
| WebSocket | `_openlaunch-ws._tcp.local.` |

## Examples

Python examples for each combination of discovery protocol and API:

| Example | API | Dependencies |
|---------|-----|--------------|
| `openapi_mdns_client.py` | OpenAPI (TCP) | `zeroconf` |
| `websocket_mdns_client.py` | WebSocket | `zeroconf`, `websockets` |

### Running the examples

Install dependencies:

```
pip install zeroconf websockets
```

Run any example:

```
python examples/openapi_mdns_client.py
```

The client will discover Nova on your network, connect, and print shot data as it arrives.
