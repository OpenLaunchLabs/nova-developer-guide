#!/usr/bin/env python3
"""
Example client for OpenLaunch WebSocket API.
Discovers the service via SSDP, connects, and prints shot/status data.

Dependencies: pip install websockets
"""

import asyncio
import json
import socket
import time

SSDP_MULTICAST_ADDR = "239.255.255.250"
SSDP_PORT = 1900
SERVICE_URN = "urn:openlaunch:service:websocket:1"


def discover_service(timeout=5.0):
    """Discover WebSocket API service via SSDP M-SEARCH."""
    print(f"Searching for {SERVICE_URN} via SSDP...")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(timeout)

    search_request = (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_MULTICAST_ADDR}:{SSDP_PORT}\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 3\r\n"
        f"ST: {SERVICE_URN}\r\n"
        "\r\n"
    )

    sock.sendto(search_request.encode(), (SSDP_MULTICAST_ADDR, SSDP_PORT))
    print("Sent SSDP M-SEARCH request...")

    start = time.time()
    while (time.time() - start) < timeout:
        try:
            data, addr = sock.recvfrom(1024)
            response = data.decode("utf-8")

            if SERVICE_URN in response:
                # Parse response headers
                headers = {}
                for line in response.split("\r\n"):
                    if ":" in line:
                        key, value = line.split(":", 1)
                        headers[key.upper().strip()] = value.strip()

                # Print all SSDP data
                print("\n=== SSDP Response ===")
                print(f"  From: {addr[0]}:{addr[1]}")
                for key, value in sorted(headers.items()):
                    print(f"  {key}: {value}")
                print()

                # Extract host:port from LOCATION header
                location = headers.get("LOCATION", "")
                location = location.replace("http://", "").replace("ws://", "").rstrip("/")
                if ":" in location:
                    host, port = location.split(":")
                    sock.close()
                    return host, int(port)

        except socket.timeout:
            break

    sock.close()
    return None, None


async def connect_and_listen(host, port):
    """Connect to WebSocket API server and print messages."""
    import websockets

    uri = f"ws://{host}:{port}"
    print(f"Connecting to {uri}...")

    async with websockets.connect(uri) as ws:
        print("Connected! Waiting for messages...\n")

        try:
            async for message in ws:
                data = json.loads(message)
                msg_type = data.get("type", "unknown")

                if msg_type == "shot":
                    print(f"Shot #{data['shot_number']}:")
                    print(f"  Speed: {data['ball_speed_meters_per_second']:.1f} m/s")
                    print(f"  VLA: {data['vertical_launch_angle_degrees']:.1f}°")
                    print(f"  HLA: {data['horizontal_launch_angle_degrees']:.1f}°")
                    print(f"  Spin: {data['total_spin_rpm']:.0f} rpm")
                    print(f"  Spin Axis: {data['spin_axis_degrees']:.1f}°")
                    print(f"  Raw: {message}")
                    print()

                elif msg_type == "status":
                    print("Status update:")
                    print(f"  Uptime: {data['uptime_seconds']}s")
                    print(f"  Firmware: {data['firmware_version']}")
                    print(f"  Shot count: {data['shot_count']}")
                    print(f"  Raw: {message}")
                    print()

                else:
                    print(f"Unknown message type: {msg_type}")
                    print(f"  Raw: {message}")
                    print()

        except websockets.ConnectionClosed:
            print("Connection closed by server")
        except KeyboardInterrupt:
            print("\nDisconnected")


def main():
    host, port = discover_service()

    if host is None:
        print("Service not found via SSDP. Connect directly to port 2920")
        return

    asyncio.run(connect_and_listen(host, port))


if __name__ == "__main__":
    main()
