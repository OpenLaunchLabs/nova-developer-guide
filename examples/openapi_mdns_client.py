#!/usr/bin/env python3
"""
Example client for OpenAPI TCP server.
Discovers the service via mDNS, connects, and prints shot data.

Dependencies: pip install zeroconf
"""

import json
import socket
import time
from zeroconf import ServiceBrowser, Zeroconf

SERVICE_TYPE = "_openapi-nova._tcp.local."


class OpenAPIListener:
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
    """Discover OpenAPI service via mDNS."""
    print(f"Searching for {SERVICE_TYPE} via mDNS...")
    zc = Zeroconf()
    listener = OpenAPIListener()
    browser = ServiceBrowser(zc, SERVICE_TYPE, listener)

    start = time.time()
    while listener.host is None and (time.time() - start) < timeout:
        time.sleep(0.1)

    browser.cancel()
    zc.close()
    return listener.host, listener.port


def extract_json_objects(buffer):
    """Extract complete JSON objects from buffer.

    Supports both newline-terminated messages and JSON boundary detection.
    Uses json.JSONDecoder.raw_decode() for proper JSON parsing.
    """
    objects = []
    decoder = json.JSONDecoder()

    # First, try newline-delimited parsing (fast path)
    while "\n" in buffer:
        line, buffer = buffer.split("\n", 1)
        line = line.strip()
        if line:
            try:
                json.loads(line)  # Validate JSON
                objects.append(line)
            except json.JSONDecodeError:
                pass  # Skip invalid JSON

    # For remaining buffer, try to parse complete JSON objects
    buffer = buffer.lstrip()
    while buffer:
        try:
            obj, end_idx = decoder.raw_decode(buffer)
            objects.append(json.dumps(obj))
            buffer = buffer[end_idx:].lstrip()
        except json.JSONDecodeError:
            break  # Incomplete JSON, wait for more data

    return objects, buffer


def connect_and_listen(host, port):
    """Connect to OpenAPI TCP server and print shots."""
    print(f"Connecting to {host}:{port}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    print("Connected! Waiting for shots...\n")

    buffer = ""
    try:
        while True:
            data = sock.recv(4096).decode("utf-8")
            if not data:
                print("Connection closed by server")
                break

            buffer += data
            objects, buffer = extract_json_objects(buffer)
            for obj_str in objects:
                shot = json.loads(obj_str)
                print(f"Shot #{shot['ShotNumber']}:")
                print(f"  Speed: {shot['BallData']['Speed']:.1f} mph")
                print(f"  VLA: {shot['BallData']['VLA']:.1f}°")
                print(f"  HLA: {shot['BallData']['HLA']:.1f}°")
                print(f"  Spin: {shot['BallData']['TotalSpin']:.0f} rpm")
                print(f"  Raw: {obj_str}")
                print()
    except KeyboardInterrupt:
        print("\nDisconnected")
    finally:
        sock.close()


def main():
    host, port = discover_service()

    if host is None:
        print("Service not found via mDNS. Try openapi_ssdp_client.py or connect directly to port 2921")
        return

    connect_and_listen(host, port)


if __name__ == "__main__":
    main()
