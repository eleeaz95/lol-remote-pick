#!/usr/bin/env python3
"""
LoL Remote Pick - Launcher & CLI Entry Point.

Starts the FastAPI backend and serves the mobile web client.
Displays local & LAN network URLs and a terminal ASCII QR Code
for effortless smartphone camera scanning.
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
from pathlib import Path

# Ensure backend directory is importable
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

import uvicorn
import threading
import time
import webbrowser
from backend.config import Settings
from backend.server import create_app, generate_ascii_qr, get_all_lan_ips, get_best_lan_ip, get_local_ip

def is_port_available(host: str, port: int) -> bool:
    """Checks if a TCP port is available to bind."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True
    except Exception:
        return False


def find_available_port(host: str, preferred_port: int, max_attempts: int = 10) -> int:
    """Returns preferred_port if available, or finds the next open port."""
    if is_port_available(host, preferred_port):
        return preferred_port

    logger.warning("Port %d is already in use by another application. Searching for next available port...", preferred_port)
    for p in range(preferred_port + 1, preferred_port + max_attempts):
        if is_port_available(host, p):
            logger.info("Found available port: %d", p)
            return p
    return preferred_port
# Configure logging format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("launcher")


def print_banner(host: str, port: int, mock_mode: bool, local_ip: str) -> None:
    """Prints the styled ASCII startup banner with LAN URLs, QR code, and tips."""
    pc_url = f"http://localhost:{port}"
    lan_url = f"http://{local_ip}:{port}"
    mode_text = "SIMULATION / MOCK LCU" if mock_mode else "LIVE LEAGUE CLIENT (LCU)"

    all_lan = get_all_lan_ips()
    alt_urls = []
    for item in all_lan:
        ip = item["ip"]
        if ip != local_ip and ip != "127.0.0.1":
            iface_name = item.get("interface", "Adapter")
            iface_type = item.get("type", "LAN")
            alt_urls.append(f"   * http://{ip}:{port} ({iface_name} - {iface_type})")

    banner = rf"""
================================================================================
  _        _        ____                      _         ____  _      _    
 | |   ___| |      |  _ \ ___ _ __ ___   ___ | |_ ___  |  _ \(_) ___| | __
 | |  / _ \ |      | |_) / _ \ '_ ` _ \ / _ \| __/ _ \ | |_) | |/ __| |/ /
 | |__| (_) |___   |  _ <  __/ | | | | | (_) | ||  __/ |  __/| | (__|   < 
 |_____\___/_____| |_| \_\___|_| |_| |_|\___/ \__\___| |_|   |_|\___|_|\_\
================================================================================
 [MODE]         : {mode_text}
 [PC BROWSER]   : {pc_url}
 [PHONE URL]    : {lan_url}
"""
    if alt_urls:
        banner += " [OTHER LAN IPs]:\n" + "\n".join(alt_urls) + "\n"

    banner += rf"""================================================================================
 📱 Scan QR Code with your Smartphone Camera (same Wi-Fi network):
"""
    print(banner)
    qr_ascii = generate_ascii_qr(lan_url)
    print(qr_ascii)
    print("""
 💡 Tips for sharing & mobile connection on Windows:
    1. Make sure your smartphone and PC are connected to the SAME Wi-Fi network.
    2. If your phone cannot open the page, allow Python / port in Windows Firewall.
    3. Open http://localhost:{port} on your PC to see the in-app QR code & lobby.
================================================================================
""".replace("{port}", str(port)))

def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="LoL Remote Pick - Control League of Legends from your phone"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host address to bind the server (default: 0.0.0.0)",
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=8000,
        help="Port to run the web server on (default: 8000)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        default=False,
        help="Run in mock LCU simulation mode without needing the real League Client",
    )
    parser.add_argument(
        "--mock-port",
        type=int,
        default=8888,
        help="Port for internal Mock LCU server (default: 8888)",
    )
    parser.add_argument(
        "--no-auto-progress",
        action="store_true",
        default=False,
        help="Disable automatic phase progression in mock mode",
    )
    parser.add_argument(
        "--ddragon-version",
        type=str,
        default="14.24.1",
        help="DataDragon version for champion and spell assets (default: 14.24.1)",
    )
    parser.add_argument(
        "--league-path",
        type=str,
        default=None,
        help="Custom path to League of Legends directory or lockfile",
    )
    parser.add_argument(
        "--open",
        "--open-browser",
        dest="open_browser",
        action="store_true",
        default=False,
        help="Automatically open the web app in your default browser on startup",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=False,
        help="Enable auto-reload for development",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point for the launcher."""
    args = parse_args()

    # Determine available port
    effective_port = find_available_port(args.host, args.port)

    # Build settings from CLI arguments
    settings = Settings(
        host=args.host,
        port=effective_port,
        mock_mode=args.mock,
        mock_port=args.mock_port,
        mock_auto_progress=not args.no_auto_progress,
        ddragon_version=args.ddragon_version,
        custom_league_path=args.league_path,
    )
    local_ip = get_best_lan_ip()
    print_banner(
        host=settings.host,
        port=settings.port,
        mock_mode=settings.mock_mode,
        local_ip=local_ip,
    )

    if args.open_browser:
        def _delayed_open():
            time.sleep(1.0)
            try:
                webbrowser.open(f"http://localhost:{settings.port}")
            except Exception:
                pass
        threading.Thread(target=_delayed_open, daemon=True).start()

    app = create_app(settings)

    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info",
        access_log=True,
    )

if __name__ == "__main__":
    main()
