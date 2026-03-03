#!/usr/bin/env python3
"""
Probe Antigravity's local endpoints and CLI to determine
the best integration strategy for OpenCode.

Run: python3 probe_antigravity.py
"""
import subprocess
import json
import sys
import time
import os
import re

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

ANTIGRAVITY_CLI = os.path.expanduser(
    "~/.antigravity/antigravity/bin/antigravity"
)


def banner(msg: str) -> None:
    """Print a formatted section banner."""
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}\n")


def probe_cli() -> dict:
    """Test if antigravity chat can be used non-interactively.

    Returns:
        dict with probe results for CLI capabilities.
    """
    banner("PHASE 1: CLI Probe")
    results = {}

    # Test 1: Chat help
    print("[1/3] Testing: antigravity chat --help")
    try:
        result = subprocess.run(
            [ANTIGRAVITY_CLI, "chat", "--help"],
            capture_output=True, text=True, timeout=10
        )
        print(f"  Exit code: {result.returncode}")
        print(f"  Stdout: {result.stdout[:500]}")
        has_modes = (
            "-m" in result.stdout or "--mode" in result.stdout
        )
        results["chat_help"] = {
            "exit_code": result.returncode,
            "has_modes": has_modes,
            "modes": [],
        }
        # Extract available modes
        for line in result.stdout.split("\n"):
            lower = line.lower()
            if "ask" in lower or "edit" in lower:
                results["chat_help"]["modes"].append(
                    line.strip()
                )
    except subprocess.TimeoutExpired:
        print("  TIMEOUT - command did not return in 10s")
        results["chat_help"] = {"error": "timeout"}
    except FileNotFoundError:
        print("  CLI binary not found")
        results["chat_help"] = {"error": "not found"}
    except OSError as e:
        print(f"  OS error: {e}")
        results["chat_help"] = {"error": str(e)}

    # Test 2: Main help for server/api/headless keywords
    print("\n[2/3] Testing: antigravity --help")
    try:
        result = subprocess.run(
            [ANTIGRAVITY_CLI, "--help"],
            capture_output=True, text=True, timeout=10
        )
        keywords = [
            "serve", "server", "api",
            "headless", "pipe", "tunnel", "proxy",
        ]
        interesting = []
        for line in result.stdout.split("\n"):
            if any(kw in line.lower() for kw in keywords):
                interesting.append(line.strip())
                print(f"  INTERESTING: {line.strip()}")
        results["main_help"] = {
            "interesting_lines": interesting,
        }
        if not interesting:
            print("  No server/API/headless keywords found")
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"  Error: {e}")
        results["main_help"] = {"error": str(e)}

    # Test 3: Version info
    print("\n[3/3] Testing: antigravity --version")
    try:
        result = subprocess.run(
            [ANTIGRAVITY_CLI, "--version"],
            capture_output=True, text=True, timeout=5
        )
        version = result.stdout.strip()
        print(f"  Version: {version}")
        results["version"] = version
    except (subprocess.TimeoutExpired, OSError) as e:
        results["version"] = str(e)

    return results


def probe_ports() -> dict:
    """Probe known Antigravity ports for endpoints.

    Returns:
        dict with port probe results.
    """
    banner("PHASE 2: Port/Endpoint Probe")
    results = {}

    # Find all Antigravity listening ports
    print("[1/2] Finding all Antigravity listening ports...")
    try:
        result = subprocess.run(
            ["lsof", "-i", "-P", "-n"],
            capture_output=True, text=True, timeout=10
        )
        ports = set()
        for line in result.stdout.split("\n"):
            if "Antigravi" in line and "LISTEN" in line:
                parts = line.split(":")
                port_str = parts[-1].split()[0]
                if port_str and port_str.isdigit():
                    ports.add(int(port_str))
                    print(f"  Found port: {port_str}")
        results["listening_ports"] = sorted(ports)
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"  Error: {e}")
        results["listening_ports"] = []

    if not HAS_REQUESTS:
        print("  requests library not available")
        return results

    # Probe each port with common endpoints
    for port in sorted(results.get("listening_ports", [])):
        port_results = {}
        print(f"\n[2/2] Probing port {port}...")
        endpoints = [
            "/v1/models",
            "/v1/chat/completions",
            "/api/models",
            "/",
            "/health",
        ]
        for ep in endpoints:
            try:
                r = requests.get(
                    f"http://localhost:{port}{ep}",
                    timeout=3,
                )
                if r.status_code != 404:
                    body = r.text[:100]
                    print(
                        f"  GET {ep} -> "
                        f"{r.status_code}: {body}"
                    )
                    port_results[f"GET {ep}"] = {
                        "status": r.status_code,
                        "body": r.text[:200],
                    }
            except requests.ConnectionError:
                pass
            except requests.Timeout:
                print(f"  GET {ep} -> timeout")
        results[f"port_{port}"] = port_results

    return results


def probe_extension_servers() -> list:
    """Extract extension server info from processes.

    Returns:
        list of dicts with extension server details.
    """
    banner("PHASE 3: Extension Server Probe")
    servers = []

    try:
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"  Error listing processes: {e}")
        return servers

    for line in result.stdout.split("\n"):
        if "language_server" not in line:
            continue
        if "extension_server_port" not in line:
            continue

        port_match = re.search(
            r"--extension_server_port\s+(\d+)", line
        )
        ext_csrf_match = re.search(
            r"--extension_server_csrf_token\s+(\S+)", line
        )
        ws_match = re.search(
            r"--workspace_id\s+(\S+)", line
        )
        endpoint_match = re.search(
            r"--cloud_code_endpoint\s+(\S+)", line
        )

        port = (
            port_match.group(1) if port_match else None
        )
        ws = ws_match.group(1) if ws_match else None
        server = {
            "extension_server_port": port,
            "csrf_token": "[REDACTED]",
            "extension_csrf_token": "[REDACTED]",
            "workspace_id": ws,
            "cloud_endpoint": (
                endpoint_match.group(1)
                if endpoint_match else None
            ),
        }
        # Keep raw ext CSRF token in memory for probing
        # but never write it to disk
        _raw_ext_csrf = (
            ext_csrf_match.group(1)
            if ext_csrf_match else None
        )
        servers.append(server)
        print(f"  Server: port={port}, workspace={ws}")

        # Try authenticated request
        if not HAS_REQUESTS:
            continue
        if not (port and _raw_ext_csrf):
            continue

        csrf = _raw_ext_csrf
        try:
            r = requests.get(
                f"http://localhost:{port}/",
                headers={"X-CSRF-Token": csrf},
                timeout=3,
            )
            print(
                f"    GET / with ext CSRF -> "
                f"{r.status_code}: {r.text[:80]}"
            )
            server["ext_csrf_response"] = {
                "status": r.status_code,
                "body": r.text[:200],
            }
        except requests.ConnectionError:
            print(f"    Connection refused on port {port}")
        except requests.Timeout:
            print(f"    Timeout on port {port}")

    return servers


def probe_summary(
    cli_results: dict,
    port_results: dict,
    servers: list,
) -> str:
    """Generate a summary with recommendations.

    Args:
        cli_results: Results from CLI probe.
        port_results: Results from port probe.
        servers: List of extension server info.

    Returns:
        Summary string with recommended approach.
    """
    banner("SUMMARY & RECOMMENDATION")

    chat_help = cli_results.get("chat_help", {})
    has_modes = chat_help.get("has_modes", False)
    ports = port_results.get("listening_ports", [])
    version = cli_results.get("version", "unknown")

    lines = [
        f"CLI chat subcommand: {'YES' if has_modes else 'NO'}",
        f"Listening ports: {ports}",
        f"Extension servers found: {len(servers)}",
        f"Version: {version}",
        "",
        "RECOMMENDED: CLI Wrapper Proxy (Approach A)",
        "  - antigravity chat CLI available",
        "  - Build Python HTTP server wrapping CLI",
        "  - Expose as /v1/chat/completions",
        "  - Note: CLI opens GUI, needs management",
    ]

    summary = "\n".join(lines)
    print(summary)
    return summary


if __name__ == "__main__":
    print("Antigravity Integration Probe")
    print(f"CLI path: {ANTIGRAVITY_CLI}")
    print(f"CLI exists: {os.path.exists(ANTIGRAVITY_CLI)}")
    print(f"requests available: {HAS_REQUESTS}")

    if not os.path.exists(ANTIGRAVITY_CLI):
        print("ERROR: Antigravity CLI not found!")
        sys.exit(1)

    cli_results = probe_cli()
    port_results = probe_ports()
    servers = probe_extension_servers()
    summary = probe_summary(
        cli_results, port_results, servers
    )

    # Save results
    results = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "cli": cli_results,
        "ports": port_results,
        "extension_servers": servers,
        "summary": summary,
    }
    output_file = "probe_results.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {output_file}")
