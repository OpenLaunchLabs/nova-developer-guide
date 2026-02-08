#!/usr/bin/env python3
"""
Nova Golf Shot Publisher (Simulator)

Simulates a Nova launch monitor by publishing golf shots every 20 seconds.
Implements mDNS discovery and both socket types (TCP/OpenAPI and WebSocket).

Dependencies: pip install zeroconf websockets
"""

import argparse
import asyncio
import json
import random
import socket
import time
from typing import Set
import websockets
from zeroconf import ServiceInfo
from zeroconf.asyncio import AsyncZeroconf

WS_PORT = 2920
TCP_PORT = 2921

MDNS_OPENAPI_TYPE = "_openapi-nova._tcp.local."
MDNS_WS_TYPE = "_openlaunch-ws._tcp.local."

SHOT_INTERVAL_SECONDS = 20
STATUS_INTERVAL_SECONDS = 5
VERSION = "simulator-2025-Dec-02"
SERIAL = "B0100SIM"
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

    def __init__(self, local_ip: str, serial: str):
        self.local_ip = local_ip
        self.serial = serial
        self.aiozc = None
        self.services = []

    async def start(self):
        self.aiozc = AsyncZeroconf()
        ip_bytes = socket.inet_aton(self.local_ip)

        # Instance name matches live hardware format: "NOVA B0100214"
        instance_name = f"NOVA {self.serial}"

        # mDNS server field uses actual machine hostname so the device is connectable
        machine_hostname = socket.gethostname().split(".")[0]

        # TXT record properties matching real hardware format
        txt_properties = {
            "model": MODEL,
            "manufacturer": MANUFACTURER,
            "serial": self.serial,
            "hostname": machine_hostname,
            "version": VERSION,
        }

        # Register OpenAPI service
        openapi_info = ServiceInfo(
            MDNS_OPENAPI_TYPE,
            f"{instance_name}.{MDNS_OPENAPI_TYPE}",
            addresses=[ip_bytes],
            port=TCP_PORT,
            properties=txt_properties,
            server=f"{machine_hostname}.local.",
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
            server=f"{machine_hostname}.local.",
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
        tcp_count, ws_count = await client_manager.client_count()

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

        _, ws_count = await client_manager.client_count()
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
async def main(shot_interval: float, serial: str):
    """Main entry point - starts all services."""
    print("=" * 60)
    print("Nova Golf Shot Publisher (Simulator)")
    print("=" * 60)

    local_ip = get_local_ip()
    print(f"Local IP: {local_ip}")
    print(f"Serial: {serial}")
    print(f"Shot interval: {shot_interval}s")
    print()

    # Initialize components
    client_manager = ClientManager()
    shot_generator = GolfShotGenerator()

    tcp_server = TCPServer(client_manager)
    ws_server = WebSocketServer(client_manager)
    mdns_advertiser = MDNSAdvertiser(local_ip, serial)

    # Start mDNS
    await mdns_advertiser.start()

    # Start servers
    await tcp_server.start()
    await ws_server.start()

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
        "--nova-id",
        type=validate_nova_id,
        default=None,
        metavar="XXXX",
        help="4-character alphanumeric Nova ID used to build the serial "
             "(e.g., --nova-id ab12 gives serial B0100AB12). Default serial: B0100SIM"
    )
    return parser.parse_args()


def resolve_serial(args) -> str:
    """Resolve the serial number based on command line arguments."""
    if args.nova_id is not None:
        return f"B0100{args.nova_id.upper()}"
    return SERIAL


if __name__ == "__main__":
    args = parse_args()
    serial = resolve_serial(args)
    try:
        asyncio.run(main(shot_interval=args.interval, serial=serial))
    except KeyboardInterrupt:
        # Allow graceful exit on Ctrl+C without traceback
        pass
