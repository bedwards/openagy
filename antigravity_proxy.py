#!/usr/bin/env python3
"""
Antigravity -> OpenAI-compatible proxy server.

Wraps the 'antigravity chat' CLI to expose Claude Opus 4.6
as an OpenAI-compatible API that OpenCode can consume.

Usage:
    python3 antigravity_proxy.py [--port 8462]

Then configure OpenCode to use http://localhost:8462/v1
"""
import json
import subprocess
import sys
import time
import uuid
import os
import re
import argparse
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler

ANTIGRAVITY_CLI = os.path.expanduser(
    "~/.antigravity/antigravity/bin/antigravity"
)
DEFAULT_PORT = 8462
MODEL_NAME = "claude-opus-4-6"
MODEL_DISPLAY = (
    "Claude Opus 4.6 (via Antigravity / Google AI Ultra)"
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("antigravity-proxy")


def find_extension_servers() -> list:
    """Discover running Antigravity extension servers.

    Extracts CSRF tokens and ports from language_server
    processes.

    Returns:
        List of dicts with server connection info.
    """
    servers = []
    try:
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True, text=True, timeout=5,
        )
    except subprocess.TimeoutExpired:
        logger.warning("ps aux timed out")
        return servers
    except OSError as e:
        logger.warning("Could not run ps: %s", e)
        return servers

    for line in result.stdout.split("\n"):
        if "language_server" not in line:
            continue
        if "extension_server_port" not in line:
            continue

        port_match = re.search(
            r"--extension_server_port\s+(\d+)", line
        )
        csrf_match = re.search(
            r"--csrf_token\s+(\S+)", line
        )
        ext_csrf_match = re.search(
            r"--extension_server_csrf_token\s+(\S+)",
            line,
        )
        ws_match = re.search(
            r"--workspace_id\s+(\S+)", line
        )
        servers.append({
            "port": (
                port_match.group(1)
                if port_match else None
            ),
            "csrf": (
                csrf_match.group(1)
                if csrf_match else None
            ),
            "ext_csrf": (
                ext_csrf_match.group(1)
                if ext_csrf_match else None
            ),
            "workspace": (
                ws_match.group(1)
                if ws_match else None
            ),
        })
    return servers


def call_antigravity_cli(
    prompt: str, mode: str = "ask"
) -> str:
    """Call antigravity chat CLI and return the response.

    Args:
        prompt: The prompt to send.
        mode: Chat mode (ask, edit, agent).

    Returns:
        The CLI response text, or an error message.
    """
    cmd = [ANTIGRAVITY_CLI, "chat", "-m", mode, prompt]
    logger.info(
        "Calling CLI: mode=%s, prompt=%d chars",
        mode, len(prompt),
    )
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "NO_COLOR": "1"},
        )
        if result.returncode == 0 and result.stdout.strip():
            output = result.stdout.strip()
            logger.info("CLI returned %d chars", len(output))
            return output
        if result.stderr.strip():
            err = result.stderr.strip()[:200]
            logger.error("CLI error: %s", err)
            return f"Error: {err}"
        logger.warning("CLI returned no output")
        return "Error: No output from antigravity chat"
    except subprocess.TimeoutExpired:
        logger.error("CLI timed out after 120s")
        return "Error: antigravity chat timed out"
    except FileNotFoundError:
        logger.error("CLI not found at %s", ANTIGRAVITY_CLI)
        return "Error: antigravity CLI not found"
    except OSError as e:
        logger.error("CLI OS error: %s", e)
        return f"Error: {e}"


class AntigravityProxy(BaseHTTPRequestHandler):
    """HTTP handler translating OpenAI API to CLI."""

    def do_GET(self) -> None:
        """Handle GET requests."""
        if self.path == "/v1/models":
            self._respond_json(200, {
                "object": "list",
                "data": [{
                    "id": MODEL_NAME,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "antigravity-ultra",
                    "permission": [],
                    "root": MODEL_NAME,
                    "parent": None,
                }],
            })
        elif self.path == "/health":
            servers = find_extension_servers()
            cli_exists = os.path.exists(ANTIGRAVITY_CLI)
            self._respond_json(200, {
                "status": "ok",
                "antigravity_cli": cli_exists,
                "extension_servers": len(servers),
                "model": MODEL_NAME,
            })
        elif self.path == "/":
            self._respond_json(200, {
                "name": "Antigravity Proxy",
                "version": "1.0.0",
                "model": MODEL_NAME,
                "endpoints": [
                    "/v1/models",
                    "/v1/chat/completions",
                    "/health",
                ],
            })
        else:
            self._respond_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        """Handle POST requests — chat completions."""
        if self.path != "/v1/chat/completions":
            self._respond_json(404, {"error": "not found"})
            return

        length = int(
            self.headers.get("Content-Length", 0)
        )
        body = json.loads(self.rfile.read(length))
        messages = body.get("messages", [])
        stream = body.get("stream", False)
        prompt = self._messages_to_prompt(messages)

        if stream:
            self._handle_streaming(prompt)
        else:
            self._handle_sync(prompt)

    def do_OPTIONS(self) -> None:
        """Handle CORS preflight requests."""
        self.send_response(200)
        self._send_cors_headers()
        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, OPTIONS",
        )
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization",
        )
        self.end_headers()

    def _messages_to_prompt(self, messages: list) -> str:
        """Convert OpenAI messages to a prompt string.

        Args:
            messages: List of message dicts.

        Returns:
            Formatted prompt string.
        """
        parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") for p in content
                    if p.get("type") == "text"
                )
            if role == "system":
                parts.append(
                    f"[System instruction: {content}]"
                )
            elif role == "user":
                parts.append(content)
            elif role == "assistant":
                parts.append(
                    f"[Previous response: {content}]"
                )
        return "\n\n".join(parts)

    def _handle_sync(self, prompt: str) -> None:
        """Handle non-streaming chat completion.

        Args:
            prompt: The formatted prompt.
        """
        response_text = call_antigravity_cli(prompt)
        prompt_tokens = len(prompt.split())
        completion_tokens = len(response_text.split())
        self._respond_json(200, {
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": MODEL_NAME,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": response_text,
                },
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": (
                    prompt_tokens + completion_tokens
                ),
            },
        })

    def _handle_streaming(self, prompt: str) -> None:
        """Handle streaming chat completion (SSE).

        Since the CLI returns all output at once, we
        simulate streaming by splitting into chunks.

        Args:
            prompt: The formatted prompt.
        """
        self.send_response(200)
        self.send_header(
            "Content-Type", "text/event-stream"
        )
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self._send_cors_headers()
        self.end_headers()

        response_text = call_antigravity_cli(prompt)
        cid = f"chatcmpl-{uuid.uuid4().hex[:8]}"

        # Send role chunk
        self._send_sse_chunk(cid, {
            "role": "assistant",
        }, None)

        # Stream word by word
        words = response_text.split(" ")
        for i, word in enumerate(words):
            suffix = " " if i < len(words) - 1 else ""
            self._send_sse_chunk(
                cid, {"content": word + suffix}, None
            )

        # Send final chunk
        self._send_sse_chunk(cid, {}, "stop")
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _send_sse_chunk(
        self,
        completion_id: str,
        delta: dict,
        finish_reason,
    ) -> None:
        """Send a single SSE chunk.

        Args:
            completion_id: The completion ID.
            delta: The delta content.
            finish_reason: Finish reason or None.
        """
        chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": MODEL_NAME,
            "choices": [{
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }],
        }
        data = json.dumps(chunk)
        self.wfile.write(f"data: {data}\n\n".encode())
        self.wfile.flush()

    def _respond_json(
        self, status: int, data: dict
    ) -> None:
        """Send a JSON response.

        Args:
            status: HTTP status code.
            data: Response data dict.
        """
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header(
            "Content-Type", "application/json"
        )
        self.send_header(
            "Content-Length", str(len(body))
        )
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_cors_headers(self) -> None:
        """Add CORS headers to the response."""
        self.send_header(
            "Access-Control-Allow-Origin", "*"
        )

    def log_message(
        self, format_str: str, *args
    ) -> None:
        """Custom logging using our logger.

        Args:
            format_str: Log format string (unused).
            args: Log arguments.
        """
        if args:
            logger.info(
                "%s %s",
                self.client_address[0], args[0],
            )


def main() -> None:
    """Start the Antigravity proxy server."""
    parser = argparse.ArgumentParser(
        description="Antigravity -> OpenAI proxy"
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT,
        help=f"Port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--host", type=str, default="localhost",
        help="Host to bind to (default: localhost)",
    )
    args = parser.parse_args()

    if not os.path.exists(ANTIGRAVITY_CLI):
        logger.error(
            "Antigravity CLI not found at %s",
            ANTIGRAVITY_CLI,
        )
        sys.exit(1)

    # Check for running extension servers
    servers = find_extension_servers()
    if servers:
        logger.info(
            "Found %d extension server(s)",
            len(servers),
        )
        for s in servers:
            logger.info(
                "  workspace=%s port=%s",
                s.get("workspace"), s.get("port"),
            )
    else:
        logger.warning(
            "No extension servers found. "
            "Is Antigravity running?"
        )

    server = HTTPServer(
        (args.host, args.port), AntigravityProxy
    )
    base_url = f"http://{args.host}:{args.port}"
    logger.info("Proxy listening on %s", base_url)
    logger.info("  /v1/models")
    logger.info("  /v1/chat/completions")
    logger.info("  /health")
    logger.info("CLI: %s", ANTIGRAVITY_CLI)
    logger.info("Model: %s", MODEL_NAME)

    # Print OpenCode config
    config = {
        "provider": {
            "antigravity": {
                "npm": "@ai-sdk/openai-compatible",
                "name": MODEL_DISPLAY,
                "options": {
                    "baseURL": f"{base_url}/v1",
                    "apiKey": "not-needed",
                },
                "models": {
                    MODEL_NAME: {
                        "name": MODEL_DISPLAY,
                    },
                },
            },
        },
    }
    logger.info(
        "OpenCode config:\n%s",
        json.dumps(config, indent=2),
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
