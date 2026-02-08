#!/usr/bin/env python3
"""
Example client for OpenLaunch WebSocket API.
Discovers the service via mDNS, connects, and prints shot/status data.

Dependencies: pip install zeroconf websockets
"""

import asyncio
import json
import socket
import time
from zeroconf import ServiceBrowser, Zeroconf

SERVICE_TYPE = "_openlaunch-ws._tcp.local."


class WebSocketListener:
    def __init__(self):
        self.host = None
        self.port = None
        self.info = None

    def add_service(self, zc, type_, name):
        info = zc.get_service_info(type_, name)
        if info:
            self.host = socket.inet_ntoa(info.addresses[0])
            self.port = info.port
            self.info = info

            # Print all mDNS data
            print("\n=== mDNS Service Discovered ===")
            print(f"  Name: {name}")
            print(f"  Type: {type_}")
            print(f"  Host: {self.host}:{self.port}")
            print(f"  Server: {info.server}")
            if info.properties:
                print("  TXT Records:")
                for key, value in info.properties.items():
                    # Decode bytes to string if needed
                    if isinstance(key, bytes):
                        key = key.decode("utf-8")
                    if isinstance(value, bytes):
                        value = value.decode("utf-8")
                    print(f"    {key}: {value}")
            print()

    def remove_service(self, zc, type_, name):
        pass

    def update_service(self, zc, type_, name):
        pass


def discover_service(timeout=5.0):
    """Discover WebSocket API service via mDNS."""
    print(f"Searching for {SERVICE_TYPE} via mDNS...")
    zc = Zeroconf()
    listener = WebSocketListener()
    browser = ServiceBrowser(zc, SERVICE_TYPE, listener)

    start = time.time()
    while listener.host is None and (time.time() - start) < timeout:
        time.sleep(0.1)

    browser.cancel()
    zc.close()
    return listener.host, listener.port


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
        print("Service not found via mDNS. Try connecting directly to port 2920")
        return

    asyncio.run(connect_and_listen(host, port))


if __name__ == "__main__":
    main()
