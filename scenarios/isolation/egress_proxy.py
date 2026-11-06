#!/usr/bin/env python3
"""Allow-list HTTPS proxy for benchmark containers (stdlib only).

Only `CONNECT <allowed host>:443` is relayed; every other request gets 403. Each decision is logged
as one line `ALLOW|DENY <host>:<port>` on stdout, so the harness can show what a session tried to reach.

    egress_proxy.py --port 3128 --allow api.anthropic.com other.host
"""
import argparse
import asyncio
import sys


async def pipe(reader, writer):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.close()
        except Exception:  # noqa: BLE001 - closing a broken socket
            pass


def target_of(request_line):
    """('host', port) for 'CONNECT host:port HTTP/1.1', else None."""
    parts = request_line.split()
    if len(parts) != 3 or parts[0].upper() != "CONNECT" or ":" not in parts[1]:
        return None
    host, _, port = parts[1].rpartition(":")
    if not port.isdigit():
        return None
    return host.lower().strip("[]"), int(port)


def allowed(target, allow):
    return target is not None and target[1] == 443 and target[0] in allow


async def handle(client_reader, client_writer, allow):
    try:
        head = await asyncio.wait_for(client_reader.readuntil(b"\r\n\r\n"), timeout=30)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, ConnectionError):
        client_writer.close()
        return
    line = head.split(b"\r\n", 1)[0].decode("latin-1")
    target = target_of(line)
    shown = f"{target[0]}:{target[1]}" if target else line[:120]
    if not allowed(target, allow):
        print(f"DENY {shown}", flush=True)
        client_writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
        await client_writer.drain()
        client_writer.close()
        return
    try:
        upstream_reader, upstream_writer = await asyncio.wait_for(asyncio.open_connection(*target), timeout=30)
    except (OSError, asyncio.TimeoutError):
        print(f"FAIL {shown}", flush=True)
        client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
        await client_writer.drain()
        client_writer.close()
        return
    print(f"ALLOW {shown}", flush=True)
    client_writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
    await client_writer.drain()
    await asyncio.gather(pipe(client_reader, upstream_writer), pipe(upstream_reader, client_writer))


async def serve(port, allow):
    server = await asyncio.start_server(lambda r, w: handle(r, w, allow), "0.0.0.0", port)
    async with server:
        await server.serve_forever()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=3128)
    parser.add_argument("--allow", nargs="+", required=True)
    args = parser.parse_args(argv)
    allow = {h.lower() for h in args.allow}
    print(f"egress proxy on :{args.port}, allow {sorted(allow)}", flush=True)
    try:
        asyncio.run(serve(args.port, allow))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
