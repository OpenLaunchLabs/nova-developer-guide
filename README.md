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

Nova advertises its services on the local network using two discovery protocols:

| Protocol | OpenAPI Service | WebSocket Service |
|----------|-----------------|-------------------|
| mDNS | `_openapi-nova._tcp.local.` | `_openlaunch-ws._tcp.local.` |
| SSDP | `urn:openlaunch:service:openapi:1` | `urn:openlaunch:service:websocket:1` |

Use whichever discovery protocol works best for your platform. Both return the same host and port information.

## Examples

Python examples for each combination of discovery protocol and API:

| Example | Discovery | API | Dependencies |
|---------|-----------|-----|--------------|
| `openapi_mdns_client.py` | mDNS | OpenAPI (TCP) | `zeroconf` |
| `openapi_ssdp_client.py` | SSDP | OpenAPI (TCP) | stdlib only |
| `websocket_mdns_client.py` | mDNS | WebSocket | `zeroconf`, `websockets` |
| `websocket_ssdp_client.py` | SSDP | WebSocket | `websockets` |

### Running the examples

Install dependencies:

```
pip install zeroconf websockets
```

Run any example:

```
python examples/openapi_ssdp_client.py
```

The client will discover Nova on your network, connect, and print shot data as it arrives.
