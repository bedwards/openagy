#!/usr/bin/env python3
"""
Verify which model the Gemini CLI actually uses.

Calls the Gemini CLI the same way our proxy does,
but with --output-format json to capture the raw
stats including exact model IDs, token counts,
and latency. This is the source of truth — the
stats.models section cannot be faked.

Usage:
    python3 verify_model.py
    python3 verify_model.py "Your custom prompt"
"""
import subprocess
import shutil
import sys
import os
import json
import argparse

DEFAULT_PROMPT = (
    "What model are you? State your exact "
    "model ID and version."
)


def find_gemini_cli() -> str:
    """Find the Gemini CLI binary."""
    path = shutil.which("gemini")
    if not path:
        print("ERROR: gemini CLI not found on PATH")
        print("Install: npm install -g @google/gemini-cli")
        sys.exit(1)
    return path


def call_gemini(cli: str, prompt: str) -> dict:
    """Call Gemini CLI and return parsed JSON response.

    Uses the same subprocess approach as our proxy's
    call_gemini_cli function, but adds -o json for
    model verification.

    Args:
        cli: Path to the gemini binary.
        prompt: The prompt to send.

    Returns:
        Parsed JSON response dict.
    """
    result = subprocess.run(
        [cli, "-p", prompt, "-o", "json"],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "NO_COLOR": "1"},
    )

    if result.returncode != 0:
        print(f"ERROR: Exit code {result.returncode}")
        if result.stderr.strip():
            print(f"STDERR: {result.stderr.strip()}")
        sys.exit(1)

    raw = result.stdout.strip()

    # Strip "Loaded cached credentials." prefix
    lines = raw.split("\n")
    json_start = next(
        (
            i for i, line in enumerate(lines)
            if line.strip().startswith("{")
        ),
        0,
    )
    json_text = "\n".join(lines[json_start:])

    try:
        return json.loads(json_text)
    except json.JSONDecodeError:
        print("ERROR: Could not parse JSON response")
        print(f"Raw output:\n{raw}")
        sys.exit(1)


def print_model_report(data: dict) -> None:
    """Print a clear report of which models were used.

    Args:
        data: Parsed JSON from Gemini CLI.
    """
    print("=" * 60)
    print("  GEMINI CLI MODEL VERIFICATION")
    print("=" * 60)
    print()

    response = data.get("response", "(no response)")
    print(f"Response: {response}")
    print()

    models = data.get("stats", {}).get("models", {})
    if not models:
        print("WARNING: No model stats in response")
        return

    print("Models used (from stats — source of truth):")
    print("-" * 50)
    for model_id, info in models.items():
        roles = list(info.get("roles", {}).keys())
        tokens = info.get("tokens", {})
        api = info.get("api", {})
        print(f"  Model ID : {model_id}")
        print(f"  Role(s)  : {', '.join(roles)}")
        print(f"  Requests : {api.get('totalRequests')}")
        print(
            f"  Latency  : {api.get('totalLatencyMs')}ms"
        )
        print(
            f"  Tokens   : in={tokens.get('input')}"
            f" out={tokens.get('candidates')}"
            f" total={tokens.get('total')}"
        )
        print()

    print("=" * 60)
    print("  FULL RAW JSON")
    print("=" * 60)
    print(json.dumps(data, indent=2))


def main() -> None:
    """Run model verification."""
    parser = argparse.ArgumentParser(
        description="Verify which model Gemini CLI uses"
    )
    parser.add_argument(
        "prompt", nargs="?", default=DEFAULT_PROMPT,
        help="Custom prompt to send",
    )
    args = parser.parse_args()

    cli = find_gemini_cli()
    print(f"CLI: {cli}")
    print(f"Prompt: {args.prompt}")
    print()

    data = call_gemini(cli, args.prompt)
    print_model_report(data)


if __name__ == "__main__":
    main()
