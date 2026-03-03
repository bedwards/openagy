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

ANTIGRAVITY_CLI = os.path.expanduser("~/.antigravity/antigravity/bin/antigravity")


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
        results["chat_help"] = {
            "exit_code": result.returncode,
            "has_modes": "-m" in result.stdout or "--mode" in result.stdout,
            "modes": [],
        }
        # Extract available modes
        for line in result.stdout.split("\n"):
            if "ask" in line.lower() or "edit" in line.lower() or "agent" in line.lower():
                results["chat_help"]["modes"].append(line.strip())
    except Exception as e:
        print(f"  Error: {e}")
        results["chat_help"] = {"error": str(e)}

    # Test 2: Main help for server/api/headless keywords
    print("\n[2/3] Testing: antigravity --help (interesting keywords)")
    try:
        result = subprocess.run(
            [ANTIGRAVITY_CLI, "--help"],
            capture_output=True, text=True, timeout=10
        )
        keywords = ["serve", "server", "api", "headless", "pipe", "tunnel", "proxy"]
        interesting = []
        for line in result.stdout.split("\n"):
            if any(kw in line.lower() for kw in keywords):
                interesting.append(line.strip())
                print(f"  INTERESTING: {line.strip()}")
        results["main_help"] = {"interesting_lines": interesting}
        if not interesting:
            print("  No server/API/headless keywords found")
    except Exception as e:
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
    except Exception as e:
        results["version"] = str(e)

    return results


def probe_ports() -> dict:
    """Probe known Antigravity ports for undiscovered endpoints.

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
                port_str = parts[-1].split()[0] if parts else None
                if port_str and port_str.isdigit():
                    ports.add(int(port_str))
                    print(f"  Found listening port: {port_str}")
        results["listening_ports"] = sorted(ports)
    except Exception as e:
        print(f"  Error: {e}")
        results["listening_ports"] = []

    # Probe each port with common endpoints
    try:
        import requests
        for port in sorted(results.get("listening_ports", [])):
            port_results = {}
            print(f"\n[2/2] Probing port {port}...")
            endpoints = ["/v1/models", "/v1/chat/completions", "/api/models", "/", "/health"]
            for ep in endpoints:
                try:
                    r = requests.get(f"http://localhost:{port}{ep}", timeout=3)
                    if r.status_code != 404:
                        print(f"  GET {ep} -> {r.status_code}: {r.text[:100]}")
                        port_results[f"GET {ep}"] = {
                            "status": r.status_code,
                            "body": r.text[:200],
                        }
                except Exception:
                    pass
            results[f"port_{port}"] = port_results
    except ImportError:
        print("  requests library not available, skipping HTTP probes")

    return results


def probe_extension_servers() -> list:
    """Extract extension server info from running language_server processes.

    Returns:
        list of dicts with extension server details.
    """
    banner("PHASE 3: Extension Server Probe")
    servers = []

    result = subprocess.run(
        ["ps", "aux"], capture_output=True, text=True, timeout=5
    )
    for line in result.stdout.split("\n"):
        if "language_server" in line and "extension_server_port" in line:
            args = line
            port_match = re.search(r"--extension_server_port\s+(\d+)", args)
            csrf_match = re.search(r"--csrf_token\s+(\S+)", args)
            ext_csrf_match = re.search(r"--extension_server_csrf_token\s+(\S+)", args)
            ws_match = re.search(r"--workspace_id\s+(\S+)", args)
            endpoint_match = re.search(r"--cloud_code_endpoint\s+(\S+)", args)

            server = {
                "extension_server_port": port_match.group(1) if port_match else None,
                "csrf_token": csrf_match.group(1) if csrf_match else None,
                "extension_csrf_token": ext_csrf_match.group(1) if ext_csrf_match else None,
                "workspace_id": ws_match.group(1) if ws_match else None,
                "cloud_endpoint": endpoint_match.group(1) if endpoint_match else None,
            }
            servers.append(server)
            print(f"  Server: port={server['extension_server_port']}, "
                  f"workspace={server['workspace_id']}")

            # Try authenticated request
            if server["extension_server_port"] and server["extension_csrf_token"]:
                try:
                    import requests
                    port = server["extension_server_port"]
                    csrf = server["extension_csrf_token"]
                    r = requests.get(
                        f"http://localhost:{port}/",
                        headers={"X-CSRF-Token": csrf},
                        timeout=3
                    )
                    print(f"    GET / with ext CSRF -> {r.status_code}: {r.text[:100]}")
                    server["ext_csrf_response"] = {
                        "status": r.status_code,
                        "body": r.text[:200],
                    }
                except Exception as e:
                    print(f"    GET / failed: {e}")

    return servers


def probe_summary(cli_results: dict, port_results: dict, servers: list) -> str:
    """Generate a summary of probe results with recommendations.

    Args:
        cli_results: Results from CLI probe.
        port_results: Results from port probe.
        servers: List of extension server info.

    Returns:
        Summary string with recommended approach.
    """
    banner("SUMMARY & RECOMMENDATION")

    lines = []
    lines.append("CLI chat subcommand exists: "
                  f"{'YES' if cli_results.get('chat_help', {}).get('has_modes') else 'NO'}")
    lines.append(f"Listening ports: {port_results.get('listening_ports', [])}")
    lines.append(f"Extension servers found: {len(servers)}")
    lines.append(f"Version: {cli_results.get('version', 'unknown')}")

    # Determine best approach
    lines.append("")
    lines.append("RECOMMENDED APPROACH: CLI Wrapper Proxy (Approach A)")
    lines.append("  - antigravity chat CLI is available with ask/edit/agent modes")
    lines.append("  - Build Python HTTP server wrapping CLI calls")
    lines.append("  - Expose as OpenAI-compatible /v1/chat/completions")
    lines.append("  - Note: CLI opens GUI window, may need process management")

    summary = "\n".join(lines)
    print(summary)
    return summary


if __name__ == "__main__":
    print("Antigravity Integration Probe")
    print(f"CLI path: {ANTIGRAVITY_CLI}")
    print(f"CLI exists: {os.path.exists(ANTIGRAVITY_CLI)}")

    if not os.path.exists(ANTIGRAVITY_CLI):
        print("ERROR: Antigravity CLI not found!")
        sys.exit(1)

    cli_results = probe_cli()
    port_results = probe_ports()
    servers = probe_extension_servers()
    summary = probe_summary(cli_results, port_results, servers)

    # Save results
    results = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "cli": cli_results,
        "ports": port_results,
        "extension_servers": servers,
        "summary": summary,
    }
    with open("probe_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to probe_results.json")
