"""MinSync CLI: `minsync serve|doctor|info|profiles`."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from . import profiles as profiles_mod
from .app import VERSION, MinSyncApp, standalone_health
from .config import Settings


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="minsync", description="MinSync - isolated Docker MCP executor")
    sub = p.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="run the MCP server")
    serve.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    sub.add_parser("doctor", help="diagnose Python/Docker/data-dir")
    sub.add_parser("info", help="service info")
    sub.add_parser("profiles", help="list language profiles")
    sub.add_parser("version", help="print version")
    args = p.parse_args(argv)

    if args.cmd == "version":
        print(VERSION)
        return 0
    if args.cmd == "profiles":
        print(json.dumps(profiles_mod.list_profiles(), indent=2))
        return 0

    if args.cmd in ("doctor", "info"):
        # Read-only: must not create the data dir or mark a live server's
        # running tasks as interrupted.
        try:
            settings = Settings()
        except ValueError as e:
            print(f"configuration error: {e}", file=sys.stderr)
            return 2
        health = asyncio.run(standalone_health(settings))
        print(json.dumps(health, indent=2))
        if args.cmd == "doctor" and not health["execution_ready"]:
            print(
                "\nDocker is NOT ready. On Windows 11: install Docker Desktop "
                "(WSL2 backend) from https://www.docker.com/products/docker-desktop/, "
                "start it, then run `docker version` in PowerShell and re-run doctor.",
                file=sys.stderr,
            )
            return 2
        return 0

    if args.cmd == "serve":
        try:
            app = MinSyncApp()
        except ValueError as e:
            print(f"configuration error: {e}", file=sys.stderr)
            return 2
        logging.basicConfig(stream=sys.stderr, level=logging.INFO)
        if args.transport == "streamable-http":
            if not (1 <= args.port <= 65535):
                raise SystemExit(f"invalid port: {args.port}")
            if args.host not in ("127.0.0.1", "localhost", "::1"):
                # v1 deliberately has no built-in auth; refusing non-loopback
                # bind instead of exposing an unauthenticated executor.
                raise SystemExit(
                    "Refusing non-loopback bind: MinSync v1 HTTP has no built-in auth. "
                    "Bind 127.0.0.1 and use a separately secured tunnel/proxy if needed."
                )
            from .server import create_server

            create_server(app, host=args.host, port=args.port).run(transport="streamable-http")
        else:
            from .server import create_server

            create_server(app).run(transport="stdio")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
