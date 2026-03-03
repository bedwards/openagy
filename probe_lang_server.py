#!/usr/bin/env python3
"""
Probe the Antigravity language_server_macos_x64
extension server to discover its protocol and achieve
a successful interaction.

Discovers all listening ports across both the
Antigravity parent process and language_server child
processes, then probes each with multiple protocols.

Key findings so far:
- extension_server_port (CSRF-protected, parent PID)
- Language server ports: HTTPS/H2 + HTTP + gRPC
- Parent "extra" ports: Chrome DevTools MCP (JSON-RPC)

Usage:
    python3 probe_lang_server.py
    python3 probe_lang_server.py --workspace openagy
    python3 probe_lang_server.py --all
"""
import subprocess
import re
import sys
import ssl
import json
import http.client
import argparse

DEFAULT_WORKSPACE = "openagy"

MCP_INIT = json.dumps({
    "jsonrpc": "2.0",
    "method": "initialize",
    "id": 1,
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {
            "name": "openagy-probe", "version": "0.1",
        },
    },
})


def discover_servers() -> list:
    """Find running language_server processes.

    Returns:
        List of dicts with port, csrf, ext_csrf,
        workspace, and pipe_path.
    """
    try:
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []

    servers = []
    for line in result.stdout.splitlines():
        if "language_server_macos" not in line:
            continue
        if "grep" in line:
            continue

        port_m = re.search(
            r"--extension_server_port\s+(\d+)", line
        )
        csrf_m = re.search(
            r"--csrf_token\s+(\S+)", line
        )
        ext_csrf_m = re.search(
            r"--extension_server_csrf_token\s+(\S+)",
            line,
        )
        ws_m = re.search(
            r"--workspace_id\s+(\S+)", line
        )

        if port_m:
            servers.append({
                "port": int(port_m.group(1)),
                "csrf": csrf_m.group(1) if csrf_m
                else None,
                "ext_csrf": ext_csrf_m.group(1)
                if ext_csrf_m else None,
                "workspace": ws_m.group(1) if ws_m
                else "(none)",
            })
    return servers


def discover_ports(ext_port: int) -> dict:
    """Use lsof to find all ports for the Antigravity
    parent and language_server child processes associated
    with a given extension_server_port.

    Returns:
        Dict with 'parent' and 'child' port lists.
    """
    # Find PID that owns the extension_server_port
    try:
        result = subprocess.run(
            ["lsof", "-i", f":{ext_port}", "-n", "-P"],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return {"parent": [], "child": []}

    parent_pid = None
    for line in result.stdout.splitlines():
        if "LISTEN" in line:
            parts = line.split()
            parent_pid = parts[1]
            break

    if not parent_pid:
        return {"parent": [], "child": []}

    ports = {"parent": [], "child": []}

    # Find all ports for parent PID
    try:
        result = subprocess.run(
            ["lsof", "-p", parent_pid, "-i", "-n",
             "-P"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if "LISTEN" in line:
                m = re.search(r":(\d+)\s", line)
                if m:
                    p = int(m.group(1))
                    ports["parent"].append(p)
    except (subprocess.TimeoutExpired, OSError):
        pass

    # Find language_server child by checking port+1
    child_port = ext_port + 1
    try:
        result = subprocess.run(
            ["lsof", "-i", f":{child_port}", "-n",
             "-P"],
            capture_output=True, text=True, timeout=5,
        )
        child_pid = None
        for line in result.stdout.splitlines():
            if "LISTEN" in line and "language_" in line:
                parts = line.split()
                child_pid = parts[1]
                break

        if child_pid:
            result = subprocess.run(
                ["lsof", "-p", child_pid, "-i", "-n",
                 "-P"],
                capture_output=True, text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                if "LISTEN" in line:
                    m = re.search(r":(\d+)\s", line)
                    if m:
                        p = int(m.group(1))
                        ports["child"].append(p)
    except (subprocess.TimeoutExpired, OSError):
        pass

    return ports


def try_mcp_init(
    host: str, port: int, use_https: bool = False
) -> dict:
    """Try MCP initialize on a port.

    Returns dict with 'success', 'server_info',
    or 'error'.
    """
    try:
        headers = {
            "Content-Type": "application/json",
            "Accept": (
                "application/json, text/event-stream"
            ),
        }
        if use_https:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            conn = http.client.HTTPSConnection(
                host, port, timeout=3, context=ctx
            )
        else:
            conn = http.client.HTTPConnection(
                host, port, timeout=3
            )

        conn.request(
            "POST", "/", body=MCP_INIT,
            headers=headers,
        )
        resp = conn.getresponse()
        body = resp.read().decode(
            "utf-8", errors="replace"
        )

        if resp.status == 200 and "event: message" in body:
            # Parse SSE data line
            for line in body.split("\n"):
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    server_info = data.get(
                        "result", {}
                    ).get("serverInfo", {})
                    return {
                        "success": True,
                        "status": resp.status,
                        "server_info": server_info,
                    }
        return {
            "success": False,
            "status": resp.status,
            "body": body[:200],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def try_http_probe(
    host: str, port: int, use_https: bool = False
) -> dict:
    """Quick HTTP/HTTPS probe to check if port responds.

    Returns dict with status and content-type.
    """
    try:
        if use_https:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            conn = http.client.HTTPSConnection(
                host, port, timeout=2, context=ctx
            )
        else:
            conn = http.client.HTTPConnection(
                host, port, timeout=2
            )
        conn.request("GET", "/", headers={})
        resp = conn.getresponse()
        body = resp.read().decode(
            "utf-8", errors="replace"
        )[:200]
        return {
            "status": resp.status,
            "content_type": resp.getheader(
                "content-type", ""
            ),
            "body": body,
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def probe_server(server: dict) -> None:
    """Run protocol discovery against one server.

    Args:
        server: Dict from discover_servers().
    """
    ext_port = server["port"]
    host = "127.0.0.1"

    print(f"\n{'=' * 60}")
    print(f"  WORKSPACE: {server['workspace']}")
    print(f"  EXT PORT: {ext_port}")
    print(f"  CSRF: {server['csrf']}")
    print(f"  EXT CSRF: {server['ext_csrf']}")
    print(f"{'=' * 60}")

    # Discover all ports
    ports = discover_ports(ext_port)
    all_parent = sorted(set(ports["parent"]))
    all_child = sorted(set(ports["child"]))

    print(
        f"\n  Parent ports: {all_parent}"
    )
    print(
        f"  Child  ports: {all_child}"
    )

    # Probe each port
    for label, port_list in [
        ("PARENT", all_parent),
        ("CHILD", all_child),
    ]:
        for port in port_list:
            print(f"\n  --- {label} port {port} ---")

            # HTTP probe
            r = try_http_probe(host, port, False)
            if "error" in r:
                http_status = f"err: {r['error'][:40]}"
            else:
                http_status = (
                    f"{r['status']} "
                    f"ct={r['content_type']}"
                )
            print(f"    HTTP:  {http_status}")

            # HTTPS probe
            r = try_http_probe(host, port, True)
            if "error" in r:
                https_status = (
                    f"err: {r['error'][:40]}"
                )
            else:
                https_status = (
                    f"{r['status']} "
                    f"ct={r['content_type']}"
                )
            print(f"    HTTPS: {https_status}")

            # MCP init (HTTP)
            r = try_mcp_init(host, port, False)
            if r.get("success"):
                si = r["server_info"]
                print(
                    f"    MCP(HTTP):  SUCCESS "
                    f"name={si.get('name')} "
                    f"v={si.get('version')}"
                )
            elif "error" in r:
                print(
                    f"    MCP(HTTP):  "
                    f"{r['error'][:60]}"
                )
            else:
                body = r.get("body", "")[:80]
                print(
                    f"    MCP(HTTP):  "
                    f"{r.get('status')} {body}"
                )

            # MCP init (HTTPS)
            r = try_mcp_init(host, port, True)
            if r.get("success"):
                si = r["server_info"]
                print(
                    f"    MCP(HTTPS): SUCCESS "
                    f"name={si.get('name')} "
                    f"v={si.get('version')}"
                )
            elif "error" in r:
                print(
                    f"    MCP(HTTPS): "
                    f"{r['error'][:60]}"
                )
            else:
                body = r.get("body", "")[:80]
                print(
                    f"    MCP(HTTPS): "
                    f"{r.get('status')} {body}"
                )


def main() -> None:
    """Discover servers and probe them."""
    parser = argparse.ArgumentParser(
        description="Probe Antigravity extension servers"
    )
    parser.add_argument(
        "--workspace", default=DEFAULT_WORKSPACE,
        help="Workspace substring to match",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Probe all servers, not just matching",
    )
    args = parser.parse_args()

    servers = discover_servers()
    if not servers:
        print("No language servers found!")
        sys.exit(1)

    print(f"Found {len(servers)} server(s):")
    for s in servers:
        print(
            f"  port={s['port']} "
            f"workspace={s['workspace']}"
        )

    if args.all:
        targets = servers
    else:
        targets = [
            s for s in servers
            if args.workspace in s.get("workspace", "")
        ]
        if not targets:
            print(
                f"\nNo server matching "
                f"'{args.workspace}'. "
                f"Using first server."
            )
            targets = [servers[0]]

    for server in targets:
        probe_server(server)


if __name__ == "__main__":
    main()
