#!/usr/bin/env python3
"""
Nova Golf Shot Publisher (Simulator)

Simulates a Nova launch monitor by publishing golf shots every 20 seconds.
Implements both discovery mechanisms (mDNS and SSDP) and both socket types
(TCP/OpenAPI and WebSocket).

Dependencies: pip install zeroconf websockets
"""

import argparse
import asyncio
import json
import random
import socket
import struct
import time
from typing import Set
import websockets
from zeroconf import ServiceInfo
from zeroconf.asyncio import AsyncZeroconf

WS_PORT = 2920
TCP_PORT = 2921

MDNS_OPENAPI_TYPE = "_openapi-nova._tcp.local."
MDNS_WS_TYPE = "_openlaunch-ws._tcp.local."

SSDP_MULTICAST_ADDR = "239.255.255.250"
SSDP_PORT = 1900
SSDP_OPENAPI_URN = "urn:openlaunch:service:openapi:1"
SSDP_WS_URN = "urn:openlaunch:service:websocket:1"

SHOT_INTERVAL_SECONDS = 20
STATUS_INTERVAL_SECONDS = 5
DEFAULT_HOSTNAME = "openlaunch-novaxsim"
VERSION = "simulator-2025-Dec-02"
FRIENDLY_NAME = "NOVA by Open Launch (Simulator)"
MANUFACTURER = "Open Launch"
MODEL = "NOVA"


# =============================================================================
# Golf Shot Generator
# =============================================================================
class GolfShotGenerator:
    """Generates realistic random golf shot data."""

    def __init__(self):
        self.shot_number = 0

    def generate_shot(self) -> dict:
        """Generate a random shot with realistic values."""
        self.shot_number += 1

        ball_speed_mph = random.uniform(2.2, 210.67)  # mph
        ball_speed_mps = ball_speed_mph * 0.44704  # convert to m/s

        max_vla = 55 if ball_speed_mph < 80 else 30
        vla = random.uniform(-10, max_vla)  # Vertical launch angle (degrees)
        hla = random.gauss(-8, 8)  # Horizontal launch angle (degrees)

        max_spin = 13000 if ball_speed_mph < 100 else 5000
        total_spin = random.uniform(1000, max_spin)  # rpm
        spin_axis = random.gauss(-30, 30)  # degrees

        return {
            "shot_number": self.shot_number,
            "ball_speed_mph": ball_speed_mph,
            "ball_speed_mps": ball_speed_mps,
            "vla": vla,
            "hla": hla,
            "total_spin": total_spin,
            "spin_axis": spin_axis,
        }

    def to_openapi_format(self, shot: dict) -> str:
        """Convert to OpenAPI (TCP) JSON format."""
        return (
            # OpenAPI messages are not guaranteed to be newline-terminated,
            # but I try to do so to make it easier for users to parse.
            json.dumps(
                {
                    "ShotNumber": shot["shot_number"],
                    "BallData": {
                        "Speed": shot["ball_speed_mph"],
                        "VLA": shot["vla"],
                        "HLA": shot["hla"],
                        "TotalSpin": shot["total_spin"],
                    },
                }
            )
            + "\n"
        )

    def to_websocket_format(self, shot: dict) -> str:
        """Convert to WebSocket JSON format."""
        return json.dumps(
            {
                "type": "shot",
                "shot_number": shot["shot_number"],
                "ball_speed_meters_per_second": shot["ball_speed_mps"],
                "vertical_launch_angle_degrees": shot["vla"],
                "horizontal_launch_angle_degrees": shot["hla"],
                "total_spin_rpm": shot["total_spin"],
                "spin_axis_degrees": shot["spin_axis"],
            }
        )


# =============================================================================
# Client Manager
# =============================================================================
class ClientManager:
    """Manages connected TCP and WebSocket clients."""

    def __init__(self):
        self.tcp_clients: Set[asyncio.StreamWriter] = set()
        self.ws_clients: Set = set()
        self._lock = asyncio.Lock()

    async def add_tcp_client(self, writer: asyncio.StreamWriter):
        async with self._lock:
            self.tcp_clients.add(writer)

    async def remove_tcp_client(self, writer: asyncio.StreamWriter):
        async with self._lock:
            self.tcp_clients.discard(writer)

    async def add_ws_client(self, ws):
        async with self._lock:
            self.ws_clients.add(ws)

    async def remove_ws_client(self, ws):
        async with self._lock:
            self.ws_clients.discard(ws)

    async def broadcast_tcp(self, message: str):
        """Send message to all TCP clients."""
        async with self._lock:
            disconnected = []
            for writer in self.tcp_clients:
                try:
                    writer.write(message.encode())
                    await writer.drain()
                except Exception as e:
                    print(f"[TCP] Error broadcasting to {writer.get_extra_info('peername')}: {e}")
                    disconnected.append(writer)
            for writer in disconnected:
                self.tcp_clients.discard(writer)

    async def broadcast_ws(self, message: str):
        """Send message to all WebSocket clients."""
        async with self._lock:
            disconnected = []
            for ws in self.ws_clients:
                try:
                    await ws.send(message)
                except Exception:
                    disconnected.append(ws)
            for ws in disconnected:
                self.ws_clients.discard(ws)

    async def client_count(self) -> tuple:
        async with self._lock:
            return len(self.tcp_clients), len(self.ws_clients)


# =============================================================================
# TCP Server
# =============================================================================
class TCPServer:
    """Asyncio-based TCP server for OpenAPI protocol."""

    def __init__(self, client_manager: ClientManager, port: int = TCP_PORT):
        self.client_manager = client_manager
        self.port = port
        self.server = None

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        addr = writer.get_extra_info("peername")
        print(f"[TCP] Client connected: {addr}")
        await self.client_manager.add_tcp_client(writer)

        try:
            # Keep connection alive, client is receive-only
            while True:
                data = await reader.read(1024)
                if not data:
                    break
        except Exception as e:
            print(f"[TCP] Client error {addr}: {e}")
        finally:
            print(f"[TCP] Client disconnected: {addr}")
            await self.client_manager.remove_tcp_client(writer)
            writer.close()
            await writer.wait_closed()

    async def start(self):
        # Accept on any interface (0.0.0.0)
        self.server = await asyncio.start_server(
            self.handle_client, "0.0.0.0", self.port
        )
        print(f"[TCP] Server listening on port {self.port}")

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()


# =============================================================================
# WebSocket Server
# =============================================================================
class WebSocketServer:
    """WebSocket server for OpenLaunch WebSocket API."""

    def __init__(self, client_manager: ClientManager, port: int = WS_PORT):
        self.client_manager = client_manager
        self.port = port
        self.server = None

    async def handle_client(self, websocket):
        addr = websocket.remote_address
        print(f"[WS] Client connected: {addr}")
        await self.client_manager.add_ws_client(websocket)

        try:
            async for message in websocket:
                # Ignore any messages (receive-only API)
                pass
        except websockets.ConnectionClosed:
            # Client disconnected normally; no action needed.
            pass
        except Exception as e:
            print(f"[WS] Client error {addr}: {e}")
        finally:
            print(f"[WS] Client disconnected: {addr}")
            await self.client_manager.remove_ws_client(websocket)

    async def start(self):
        # Accept on any interface (0.0.0.0)
        self.server = await websockets.serve(self.handle_client, "0.0.0.0", self.port)
        print(f"[WS] Server listening on port {self.port}")

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()


# =============================================================================
# mDNS Advertiser
# =============================================================================
class MDNSAdvertiser:
    """Advertises services via mDNS using zeroconf (async API)."""

    def __init__(self, local_ip: str, hostname: str):
        self.local_ip = local_ip
        self.hostname = hostname
        self.aiozc = None
        self.services = []

    async def start(self):
        self.aiozc = AsyncZeroconf()
        ip_bytes = socket.inet_aton(self.local_ip)

        # Use friendly name for mDNS instance name (like real hardware)
        instance_name = FRIENDLY_NAME

        # TXT record properties matching real hardware format
        txt_properties = {
            "model": MODEL,
            "manufacturer": MANUFACTURER,
            "hostname": self.hostname,
            "version": VERSION,
        }

        # Register OpenAPI service
        openapi_info = ServiceInfo(
            MDNS_OPENAPI_TYPE,
            f"{instance_name}.{MDNS_OPENAPI_TYPE}",
            addresses=[ip_bytes],
            port=TCP_PORT,
            properties=txt_properties,
            server=f"{self.hostname}.local.",
        )
        await self.aiozc.async_register_service(openapi_info)
        self.services.append(openapi_info)
        print(f"[mDNS] Registered {MDNS_OPENAPI_TYPE} as '{instance_name}'")

        # Register WebSocket service
        ws_info = ServiceInfo(
            MDNS_WS_TYPE,
            f"{instance_name}.{MDNS_WS_TYPE}",
            addresses=[ip_bytes],
            port=WS_PORT,
            properties=txt_properties,
            server=f"{self.hostname}.local.",
        )
        await self.aiozc.async_register_service(ws_info)
        self.services.append(ws_info)
        print(f"[mDNS] Registered {MDNS_WS_TYPE} as '{instance_name}'")

    async def stop(self):
        if self.aiozc:
            for service in self.services:
                await self.aiozc.async_unregister_service(service)
            await self.aiozc.async_close()
            print("[mDNS] Services unregistered")


# =============================================================================
# SSDP Responder
# =============================================================================
class SSDPProtocol(asyncio.DatagramProtocol):
    """Asyncio protocol for handling SSDP multicast."""

    def __init__(self, local_ip: str, hostname: str, uuid_suffix: str):
        self.local_ip = local_ip
        self.hostname = hostname
        self.uuid_suffix = uuid_suffix
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple):
        try:
            message = data.decode("utf-8")
            if "M-SEARCH" not in message:
                return

            # Check which service is being searched for
            if SSDP_OPENAPI_URN in message or "ssdp:all" in message:
                self.send_response(addr, SSDP_OPENAPI_URN, f"http://{self.local_ip}:{TCP_PORT}/")
                print(f"[SSDP] Responded to M-SEARCH for OpenAPI from {addr}")

            if SSDP_WS_URN in message or "ssdp:all" in message:
                self.send_response(addr, SSDP_WS_URN, f"http://{self.local_ip}:{WS_PORT}/")
                print(f"[SSDP] Responded to M-SEARCH for WebSocket from {addr}")

        except Exception as e:
            print(f"[SSDP] Error handling request: {e}")

    def send_response(self, addr: tuple, st: str, location: str):
        response = (
            "HTTP/1.1 200 OK\r\n"
            "CACHE-CONTROL: max-age=1800\r\n"
            f"LOCATION: {location}\r\n"
            f"SERVER: OpenLaunch/{VERSION}\r\n"
            f"ST: {st}\r\n"
            f"USN: uuid:openlaunch-nova-{self.uuid_suffix}::{st}\r\n"
            f"X-FRIENDLY-NAME: {FRIENDLY_NAME}\r\n"
            f"X-HOSTNAME: {self.hostname}\r\n"
            f"X-MANUFACTURER: {MANUFACTURER}\r\n"
            f"X-MODEL: {MODEL}\r\n"
            f"X-VERSION: {VERSION}\r\n"
            "\r\n"
        )
        self.transport.sendto(response.encode(), addr)


class SSDPResponder:
    """Responds to SSDP M-SEARCH requests."""

    def __init__(self, local_ip: str, hostname: str):
        self.local_ip = local_ip
        self.hostname = hostname
        # Generate a UUID suffix from the IP address (like real hardware)
        self.uuid_suffix = ''.join(f'{int(x):02x}' for x in local_ip.split('.'))
        self.transport = None
        self.protocol = None

    async def start(self):
        loop = asyncio.get_event_loop()

        # Create multicast socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            # SO_REUSEPORT allows multiple sockets to bind to the same port.
            # Not available on all platforms (e.g., Windows), but not required for basic functionality.
            pass

        # Bind to SSDP port on all interfaces
        sock.bind(("", SSDP_PORT))

        # Join multicast group on all interfaces (0.0.0.0)
        mreq = struct.pack("4s4s",
                          socket.inet_aton(SSDP_MULTICAST_ADDR),
                          socket.inet_aton("0.0.0.0"))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        # Create asyncio datagram endpoint from existing socket
        self.transport, self.protocol = await loop.create_datagram_endpoint(
            lambda: SSDPProtocol(self.local_ip, self.hostname, self.uuid_suffix),
            sock=sock
        )

        print(f"[SSDP] Listening on {SSDP_MULTICAST_ADDR}:{SSDP_PORT}")

    def stop(self):
        if self.transport:
            self.transport.close()


# =============================================================================
# Shot Broadcast Task
# =============================================================================
async def shot_broadcast_task(
    client_manager: ClientManager,
    shot_generator: GolfShotGenerator,
    interval: float = SHOT_INTERVAL_SECONDS,
):
    """Periodically generate and broadcast shots."""
    print(f"[Broadcaster] Will send shots every {interval} seconds")

    while True:
        await asyncio.sleep(interval)

        shot = shot_generator.generate_shot()
        tcp_count, ws_count = client_manager.client_count

        print(
            f"\n[Shot #{shot['shot_number']}] "
            f"Speed: {shot['ball_speed_mph']:.1f} mph, "
            f"VLA: {shot['vla']:.1f}°, HLA: {shot['hla']:.1f}°, "
            f"Spin: {shot['total_spin']:.0f} rpm"
        )

        if tcp_count > 0 or ws_count > 0:
            print(f"  Broadcasting to {tcp_count} TCP + {ws_count} WS clients")

            if tcp_count > 0:
                tcp_msg = shot_generator.to_openapi_format(shot)
                await client_manager.broadcast_tcp(tcp_msg)

            if ws_count > 0:
                ws_msg = shot_generator.to_websocket_format(shot)
                await client_manager.broadcast_ws(ws_msg)
        else:
            print("  (no clients connected)")


# =============================================================================
# Status Broadcast Task (WebSocket only)
# =============================================================================
async def status_broadcast_task(
    client_manager: ClientManager,
    shot_generator: GolfShotGenerator,
    start_time: float,
    interval: float = STATUS_INTERVAL_SECONDS,
):
    """Periodically broadcast status messages to WebSocket clients."""
    while True:
        await asyncio.sleep(interval)

        _, ws_count = client_manager.client_count
        if ws_count > 0:
            uptime = int(time.time() - start_time)
            status_msg = json.dumps({
                "type": "status",
                "uptime_seconds": uptime,
                "firmware_version": VERSION,
                "shot_count": shot_generator.shot_number,
            })
            await client_manager.broadcast_ws(status_msg)


# =============================================================================
# Utilities
# =============================================================================
def get_local_ip() -> str:
    """Get the local IP address for advertising services."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't actually connect, just determines local IP
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


# =============================================================================
# Main
# =============================================================================
async def main(shot_interval: float, hostname: str):
    """Main entry point - starts all services."""
    print("=" * 60)
    print("Nova Golf Shot Publisher (Simulator)")
    print("=" * 60)

    local_ip = get_local_ip()
    print(f"Local IP: {local_ip}")
    print(f"Hostname: {hostname}")
    print(f"Shot interval: {shot_interval}s")
    print()

    # Initialize components
    client_manager = ClientManager()
    shot_generator = GolfShotGenerator()

    tcp_server = TCPServer(client_manager)
    ws_server = WebSocketServer(client_manager)
    mdns_advertiser = MDNSAdvertiser(local_ip, hostname)
    ssdp_responder = SSDPResponder(local_ip, hostname)

    # Start mDNS
    await mdns_advertiser.start()

    # Start servers
    await tcp_server.start()
    await ws_server.start()

    # Start SSDP responder (uses asyncio protocol, no task needed)
    await ssdp_responder.start()

    # Record start time for uptime calculation
    start_time = time.time()

    # Create broadcast tasks
    shot_task = asyncio.create_task(
        shot_broadcast_task(client_manager, shot_generator, interval=shot_interval)
    )
    status_task = asyncio.create_task(
        status_broadcast_task(client_manager, shot_generator, start_time)
    )

    print()
    print("=" * 60)
    print("Ready! Clients can now connect.")
    print(f"  TCP (OpenAPI): {local_ip}:{TCP_PORT}")
    print(f"  WebSocket:     {local_ip}:{WS_PORT}")
    print("Press Ctrl+C to stop")
    print("=" * 60)
    print()

    try:
        await asyncio.gather(shot_task, status_task)
    except asyncio.CancelledError:
        # Task cancellation is expected during shutdown; ignore and proceed to cleanup.
        pass
    finally:
        print("\nShutting down...")
        ssdp_responder.stop()
        shot_task.cancel()
        status_task.cancel()
        # Await cancelled tasks to ensure proper cleanup
        await asyncio.gather(shot_task, status_task, return_exceptions=True)
        await mdns_advertiser.stop()
        await tcp_server.stop()
        await ws_server.stop()
        print("Goodbye!")


def validate_nova_id(value):
    """Validate that nova-id is exactly 4 alphanumeric characters."""
    if not value.isalnum() or len(value) != 4:
        raise argparse.ArgumentTypeError(
            f"'{value}' is not valid. Must be exactly 4 alphanumeric characters."
        )
    return value.lower()


def validate_interval(value):
    """Validate that interval is a positive float."""
    try:
        fval = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Interval '{value}' is not a valid float.")
    if fval <= 0:
        raise argparse.ArgumentTypeError("Interval must be a positive number.")
    return fval

def parse_args():
    parser = argparse.ArgumentParser(
        description="Nova Golf Shot Publisher (Simulator) - simulates a Nova launch monitor"
    )
    parser.add_argument(
        "-i", "--interval",
        type=validate_interval,
        default=SHOT_INTERVAL_SECONDS,
        help=f"Interval between shots in seconds (default: {SHOT_INTERVAL_SECONDS})"
    )
    parser.add_argument(
        "--hostname",
        nargs="?",
        const="__USE_MACHINE_HOSTNAME__",
        default=None,
        help="mDNS hostname. If flag provided without value, uses machine hostname. "
             f"(default: {DEFAULT_HOSTNAME})"
    )
    parser.add_argument(
        "--nova-id",
        type=validate_nova_id,
        default=None,
        metavar="XXXX",
        help="4-character alphanumeric Nova ID, replaces 'xsim' in default hostname "
             "(e.g., --nova-id ab12 gives openlaunch-novaab12)"
    )
    return parser.parse_args()


def resolve_hostname(args) -> str:
    """Resolve the hostname based on command line arguments."""
    if args.hostname == "__USE_MACHINE_HOSTNAME__":
        # --hostname flag with no value: use machine hostname
        return socket.gethostname().split(".")[0]
    elif args.hostname is not None:
        # --hostname with explicit value
        return args.hostname
    elif args.nova_id is not None:
        # --nova-id provided: replace 'xsim' with the ID
        return f"openlaunch-nova{args.nova_id}"
    else:
        # Default hostname
        return DEFAULT_HOSTNAME


if __name__ == "__main__":
    args = parse_args()
    hostname = resolve_hostname(args)
    try:
        asyncio.run(main(shot_interval=args.interval, hostname=hostname))
    except KeyboardInterrupt:
        # Allow graceful exit on Ctrl+C without traceback
        pass
