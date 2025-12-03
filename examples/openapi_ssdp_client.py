#!/usr/bin/env python3
"""
Example client for OpenAPI TCP server.
Discovers the service via SSDP, connects, and prints shot data.

No external dependencies required (uses only stdlib).
"""

import json
import socket
import time

SSDP_MULTICAST_ADDR = "239.255.255.250"
SSDP_PORT = 1900
SERVICE_URN = "urn:openlaunch:service:openapi:1"


def discover_service(timeout=5.0):
    """Discover OpenAPI service via SSDP M-SEARCH."""
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
        print("Service not found via SSDP. Try openapi_mdns_client.py or connect directly to port 2921")
        return

    connect_and_listen(host, port)


if __name__ == "__main__":
    main()
