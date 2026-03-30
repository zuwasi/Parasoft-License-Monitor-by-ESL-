"""
ESL License Monitor Agent v1.0.0
Engineering Software Lab - DEMO

Lightweight HTTP agent that runs on a Parasoft DTP server and serves
license log files to remote ESL License Monitor instances.

Zero external dependencies — uses only Python stdlib.
"""

import argparse
import json
import logging
import os
import platform
import re
import secrets
import socket
import ssl
import subprocess
import sys
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

AGENT_VERSION = "1.0.0"
SERVICE_NAME = "ESL_License_Agent"
LOG_FILE_PATTERN = re.compile(r"^ls_access\.log(\.\d{4}-\d{2}-\d{2})?$")

DEFAULT_CONFIG = {
    "port": 9271,
    "host": "0.0.0.0",
    "token": "change-me-to-a-secure-token",
    "logs_path": r"C:\ProgramData\Parasoft\DTP\logs",
    "ssl_cert": "",
    "ssl_key": "",
}

logger = logging.getLogger("esl_agent")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def load_config(config_path: Path) -> dict:
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        merged = {**DEFAULT_CONFIG, **cfg}
        return merged

    # First run — create default config
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, indent=4)
    print(f"[INFO] Created default config at: {config_path}")
    print("[INFO] Please edit the file and set a secure token before production use.")
    return dict(DEFAULT_CONFIG)


def apply_overrides(config: dict, args: argparse.Namespace) -> dict:
    if args.port is not None:
        config["port"] = args.port
    if args.token is not None:
        config["token"] = args.token
    if args.logs_path is not None:
        config["logs_path"] = args.logs_path
    return config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def count_log_files(logs_path: Path):
    count = 0
    total_size = 0
    if logs_path.is_dir():
        for entry in logs_path.iterdir():
            if entry.is_file() and LOG_FILE_PATTERN.match(entry.name):
                count += 1
                total_size += entry.stat().st_size
    return count, total_size


def is_safe_filename(name: str) -> bool:
    if not name:
        return False
    if "/" in name or "\\" in name or ".." in name:
        return False
    return bool(LOG_FILE_PATTERN.match(name))


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class AgentHandler(BaseHTTPRequestHandler):

    server_version = f"ESL-Agent/{AGENT_VERSION}"

    def log_message(self, fmt, *args):
        logger.info("%s - %s", self.client_address[0], fmt % args)

    # --- routing ---

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = parse_qs(parsed.query)

        if path == "/api/health":
            self._handle_health()
            return

        if not self._check_auth():
            return

        if path == "/api/info":
            self._handle_info()
        elif path == "/api/logs":
            self._handle_logs(query)
        elif path.startswith("/api/logs/"):
            filename = path[len("/api/logs/"):]
            self._handle_log_file(filename)
        else:
            self._send_json({"error": "Not found"}, 404)

    # --- auth ---

    def _check_auth(self) -> bool:
        token = self.headers.get("X-Auth-Token", "")
        if token == self.server.config["token"]:
            return True
        logger.warning("Unauthorized request from %s", self.client_address[0])
        self._send_json({"error": "Unauthorized"}, 401)
        return False

    # --- endpoint handlers ---

    def _handle_health(self):
        self._send_json({"status": "ok"})

    def _handle_info(self):
        logs_path = Path(self.server.config["logs_path"])
        file_count, total_size = count_log_files(logs_path)
        self._send_json({
            "agent_version": AGENT_VERSION,
            "hostname": socket.gethostname(),
            "platform": platform.system(),
            "logs_path": str(logs_path),
            "log_file_count": file_count,
            "total_log_size_mb": round(total_size / (1024 * 1024), 2),
        })

    def _handle_logs(self, query: dict):
        logs_path = Path(self.server.config["logs_path"])
        since = query.get("since", [None])[0]

        files = []
        if logs_path.is_dir():
            for entry in sorted(logs_path.iterdir(), key=lambda e: e.name):
                if not entry.is_file() or not LOG_FILE_PATTERN.match(entry.name):
                    continue

                if since:
                    # Extract date suffix if present
                    parts = entry.name.split(".")
                    date_suffix = parts[-1] if len(parts) == 3 else None
                    # Keep current log (no date suffix) and files >= since date
                    if date_suffix and date_suffix < since:
                        continue

                stat = entry.stat()
                modified = datetime.fromtimestamp(stat.st_mtime).strftime(
                    "%Y-%m-%dT%H:%M:%S"
                )
                files.append({
                    "name": entry.name,
                    "size": stat.st_size,
                    "modified": modified,
                })

        self._send_json({"files": files})

    def _handle_log_file(self, filename: str):
        if not is_safe_filename(filename):
            self._send_json({"error": "Invalid filename"}, 400)
            return

        file_path = Path(self.server.config["logs_path"]) / filename

        if not file_path.is_file():
            self._send_json({"error": "File not found"}, 404)
            return

        file_size = file_path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(file_size))
        self.end_headers()

        # Stream in 64 KB chunks
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)

    # --- response helpers ---

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# Windows service helpers
# ---------------------------------------------------------------------------

def install_service(config_path: Path):
    exe = sys.executable
    script = Path(__file__).resolve()
    bin_path = f'"{exe}" "{script}" --config "{config_path}"'
    cmd = [
        "sc", "create", SERVICE_NAME,
        f"binPath= {bin_path}",
        "start= auto",
        f"DisplayName= ESL License Monitor Agent",
    ]
    print(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    print(f"Service '{SERVICE_NAME}' installed. Start it with: sc start {SERVICE_NAME}")


def remove_service():
    subprocess.run(["sc", "stop", SERVICE_NAME], check=False)
    subprocess.run(["sc", "delete", SERVICE_NAME], check=True)
    print(f"Service '{SERVICE_NAME}' removed.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ESL License Monitor Agent — serves Parasoft DTP license logs over HTTP.",
    )
    parser.add_argument(
        "--config", type=str, default=None,
        help="Path to config file (default: agent_config.json in script dir)",
    )
    parser.add_argument("--port", type=int, default=None, help="Override port from config")
    parser.add_argument("--token", type=str, default=None, help="Override token from config")
    parser.add_argument("--logs-path", type=str, default=None, help="Override logs path from config")
    parser.add_argument(
        "--generate-token", action="store_true",
        help="Generate a random secure token and print it",
    )
    parser.add_argument(
        "--install-service", action="store_true",
        help="Install as Windows service (using sc.exe)",
    )
    parser.add_argument(
        "--remove-service", action="store_true",
        help="Remove the Windows service",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    # One-shot commands
    if args.generate_token:
        print(secrets.token_urlsafe(32))
        return

    if args.remove_service:
        remove_service()
        return

    # Logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Config
    if args.config:
        config_path = Path(args.config).resolve()
    else:
        config_path = Path(__file__).resolve().parent / "agent_config.json"

    config = load_config(config_path)
    config = apply_overrides(config, args)

    if args.install_service:
        install_service(config_path)
        return

    # Warn about default token
    if config["token"] == DEFAULT_CONFIG["token"]:
        logger.warning("Using the default token — set a secure token before production use!")
    elif len(config["token"]) < 16:
        logger.warning("Token is shorter than 16 characters — consider using a longer token.")

    # Validate logs path
    logs_path = Path(config["logs_path"])
    if not logs_path.is_dir():
        logger.warning("Logs path does not exist: %s", logs_path)

    file_count, _ = count_log_files(logs_path)

    scheme = "https" if config.get("ssl_cert") else "http"
    banner = f"""
============================================
  ESL License Monitor Agent v{AGENT_VERSION}
  Engineering Software Lab - DEMO
============================================
  Listening on: {scheme}://{config['host']}:{config['port']}
  Logs path:    {config['logs_path']}
  Log files:    {file_count}
  Auth:         Token required
============================================"""
    print(banner)

    # Start server
    httpd = HTTPServer((config["host"], config["port"]), AgentHandler)
    httpd.config = config

    if config.get("ssl_cert") and config.get("ssl_key"):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(config["ssl_cert"], config["ssl_key"])
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
        logger.info("SSL enabled")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down.")
        httpd.server_close()


if __name__ == "__main__":
    main()
