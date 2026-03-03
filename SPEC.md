# Antigravity → OpenCode Integration Spec
> **Goal**: Enable OpenCode (CLI coding agent) to use **Claude Opus 4.6** through the locally-running **Antigravity** desktop app, which is authenticated via a **Google AI Ultra subscription**.
---
## Context & Architecture
### What is Antigravity?
Antigravity is a VS Code-based desktop IDE (Electron app) by Google DeepMind. It runs Claude Opus 4.6 via Google AI Ultra subscription — the LLM calls go through Google's infrastructure (`daily-cloudcode-pa.googleapis.com`), not directly to Anthropic.
**Key fact**: Antigravity already has a CLI:
```bash
# Located at:
/Users/bedwards/.antigravity/antigravity/bin/antigravity
# Agent mode (like cursor agent):
antigravity chat -m agent "your prompt"
# Other modes:
antigravity chat -m ask "question"
antigravity chat -m edit "instruction"
# Add file context:
antigravity chat -a path/to/file.py "your prompt"
# Pipe stdin:
cat error.log | antigravity chat "what's wrong?" -
```
### What is OpenCode?
OpenCode (v1.2.15 installed) is an open-source CLI coding agent. It supports custom providers via `~/.opencode.json`. Docs: https://opencode.ai/docs/providers
OpenCode custom provider config format:
```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "my-provider-id": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Display Name",
      "options": {
        "baseURL": "http://localhost:PORT/v1"
      },
      "models": {
        "model-id": {
          "name": "Model Display Name"
        }
      }
    }
  },
  "agents": {
    "coder": { "model": "my-provider-id.model-id", "maxTokens": 16000 },
    "task": { "model": "my-provider-id.model-id", "maxTokens": 16000 },
    "title": { "model": "my-provider-id.model-id", "maxTokens": 80 }
  }
}
```
OpenCode requires the provider to expose an **OpenAI-compatible API** (specifically `/v1/chat/completions` endpoint).
### Antigravity's Local Infrastructure (Probed)
| Port | Service | Protocol | Notes |
|------|---------|----------|-------|
| **53578** | Web UI server | HTTP (CSRF-protected) | Returns "Invalid CSRF token" on unauthenticated requests |
| **53607** | Chrome DevTools MCP | JSON-RPC + SSE (MCP protocol) | `chrome_devtools` server v0.12.1. Browser automation tools only. NOT an LLM endpoint. |
| **53625** | Extension host | HTTP | Third Antigravity subprocess, likely internal |
**Critical finding**: Antigravity does NOT expose a local OpenAI-compatible API for its LLM. The LLM calls go:
```
Antigravity renderer → language_server_macos_x64 → https://daily-cloudcode-pa.googleapis.com
```
The language server processes use CSRF tokens and connect to per-workspace extension servers:
```
language_server_macos_x64 \
  --csrf_token <UUID> \
  --extension_server_port <PORT> \
  --extension_server_csrf_token <UUID> \
  --cloud_code_endpoint https://daily-cloudcode-pa.googleapis.com \
  --workspace_id <WORKSPACE_ID>
```
### Existing Auth Credentials
File: `~/.local/share/opencode/auth.json` — contains API keys/OAuth tokens for:
- OpenRouter, Anthropic (OAuth), OpenAI, Alibaba, Google (API key), Z.AI
File: Antigravity auth — managed internally by the Electron app, tied to Google account with AI Ultra subscription.
---
## Implementation Plan
Since Antigravity doesn't expose a direct OpenAI-compatible API, we need to **build a lightweight proxy server** that:
1. Accepts OpenAI-compatible `/v1/chat/completions` requests
2. Translates them into `antigravity chat` CLI calls
3. Returns the response in OpenAI-compatible format
4. Supports streaming (SSE) for real-time output
### Phase 1: Python Probe Script
**File**: `probe_antigravity.py`
**Purpose**: Systematically discover what Antigravity exposes locally and test the `antigravity chat` CLI for programmatic use.
```python
#!/usr/bin/env python3
"""
Probe Antigravity's local endpoints and CLI to determine
the best integration strategy for OpenCode.
Run: python3 probe_antigravity.py
"""
import subprocess
import json
import requests
import sys
import time
import os
ANTIGRAVITY_CLI = os.path.expanduser("~/.antigravity/antigravity/bin/antigravity")
def banner(msg):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}\n")
def probe_cli():
    """Test if antigravity chat can be used non-interactively."""
    banner("PHASE 1: CLI Probe")
    # Test 1: Basic chat command
    print("[1/4] Testing: antigravity chat --help")
    result = subprocess.run(
        [ANTIGRAVITY_CLI, "chat", "--help"],
        capture_output=True, text=True, timeout=10
    )
    print(f"  Exit code: {result.returncode}")
    print(f"  Stdout: {result.stdout[:500]}")
    print(f"  Stderr: {result.stderr[:500]}")
    # Test 2: Non-interactive prompt (does it return output to stdout?)
    print("\n[2/4] Testing: antigravity chat -m ask 'respond with only: HELLO'")
    try:
        result = subprocess.run(
            [ANTIGRAVITY_CLI, "chat", "-m", "ask", "respond with only the word HELLO"],
            capture_output=True, text=True, timeout=30
        )
        print(f"  Exit code: {result.returncode}")
        print(f"  Stdout length: {len(result.stdout)} chars")
        print(f"  Stdout: {result.stdout[:500]}")
        print(f"  Stderr: {result.stderr[:500]}")
    except subprocess.TimeoutExpired:
        print("  TIMEOUT - command did not return in 30s")
        print("  This suggests it opens the GUI instead of running headlessly")
    # Test 3: Pipe mode
    print("\n[3/4] Testing: echo 'hello' | antigravity chat 'what is this?' -")
    try:
        result = subprocess.run(
            [ANTIGRAVITY_CLI, "chat", "what is this input?", "-"],
            input="hello world",
            capture_output=True, text=True, timeout=30
        )
        print(f"  Exit code: {result.returncode}")
        print(f"  Stdout: {result.stdout[:500]}")
    except subprocess.TimeoutExpired:
        print("  TIMEOUT")
    # Test 4: Check if there's a headless or server mode
    print("\n[4/4] Testing: antigravity --help (full output)")
    result = subprocess.run(
        [ANTIGRAVITY_CLI, "--help"],
        capture_output=True, text=True, timeout=10
    )
    for line in result.stdout.split('\n'):
        if any(kw in line.lower() for kw in ['serve', 'server', 'api', 'headless', 'pipe', 'tunnel', 'proxy']):
            print(f"  INTERESTING: {line.strip()}")
def probe_ports():
    """Probe known Antigravity ports for undiscovered endpoints."""
    banner("PHASE 2: Port/Endpoint Probe")
    # Find all Antigravity listening ports
    print("[1/3] Finding all Antigravity listening ports...")
    result = subprocess.run(
        ["lsof", "-i", "-P", "-n"],
        capture_output=True, text=True, timeout=10
    )
    ports = set()
    for line in result.stdout.split('\n'):
        if 'Antigravi' in line and 'LISTEN' in line:
            # Extract port number
            parts = line.split(':')
            port = parts[-1].split()[0] if parts else None
            if port:
                ports.add(int(port))
                print(f"  Found listening port: {port}")
    # Probe each port
    for port in sorted(ports):
        print(f"\n[2/3] Probing port {port}...")
        # Try OpenAI-compatible endpoint
        endpoints = [
            "/v1/models",
            "/v1/chat/completions",
            "/api/models",
            "/api/chat",
            "/api/generate",
            "/",
            "/health",
        ]
        for ep in endpoints:
            try:
                r = requests.get(f"http://localhost:{port}{ep}", timeout=3)
                if r.status_code != 404:
                    print(f"  GET {ep} -> {r.status_code}: {r.text[:200]}")
            except Exception as e:
                pass
            try:
                r = requests.post(
                    f"http://localhost:{port}{ep}",
                    headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
                    json={"model": "claude-opus-4-6", "messages": [{"role": "user", "content": "hello"}]},
                    timeout=3
                )
                if r.status_code != 404:
                    print(f"  POST {ep} -> {r.status_code}: {r.text[:200]}")
            except Exception as e:
                pass
        # Try MCP initialization
        print(f"\n[3/3] MCP probe on port {port}...")
        try:
            r = requests.post(
                f"http://localhost:{port}/",
                headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
                json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "probe", "version": "0.1.0"}
                    }
                },
                timeout=5
            )
            print(f"  MCP init -> {r.status_code}: {r.text[:300]}")
        except Exception as e:
            print(f"  MCP init failed: {e}")
def probe_extension_server():
    """Try to interact with the language server's extension server."""
    banner("PHASE 3: Extension Server Probe")
    # Parse process list to find extension server ports and CSRF tokens
    result = subprocess.run(
        ["ps", "aux"], capture_output=True, text=True, timeout=5
    )
    for line in result.stdout.split('\n'):
        if 'language_server' in line and 'extension_server_port' in line:
            parts = line.split()
            args = ' '.join(parts)
            # Extract extension_server_port
            import re
            port_match = re.search(r'--extension_server_port\s+(\d+)', args)
            csrf_match = re.search(r'--extension_server_csrf_token\s+(\S+)', args)
            ws_match = re.search(r'--workspace_id\s+(\S+)', args)
            if port_match:
                port = port_match.group(1)
                csrf = csrf_match.group(1) if csrf_match else "unknown"
                ws = ws_match.group(1) if ws_match else "unknown"
                print(f"  Extension server: port={port}, workspace={ws}")
                print(f"  CSRF token: {csrf}")
                # Try authenticated request
                try:
                    r = requests.get(
                        f"http://localhost:{port}/",
                        headers={"X-CSRF-Token": csrf},
                        timeout=3
                    )
                    print(f"  GET / -> {r.status_code}: {r.text[:200]}")
                except Exception as e:
                    print(f"  GET / failed: {e}")
                # Try with cookie
                try:
                    r = requests.get(
                        f"http://localhost:{port}/v1/models",
                        headers={"X-CSRF-Token": csrf},
                        timeout=3
                    )
                    print(f"  GET /v1/models -> {r.status_code}: {r.text[:200]}")
                except Exception as e:
                    print(f"  GET /v1/models failed: {e}")
def probe_cloud_endpoint():
    """See if the cloud code endpoint is accessible with the Google API key."""
    banner("PHASE 4: Cloud Code Endpoint Probe")
    # Read existing Google API key from OpenCode auth
    auth_path = os.path.expanduser("~/.local/share/opencode/auth.json")
    try:
        with open(auth_path) as f:
            auth = json.load(f)
        google_key = auth.get("google", {}).get("key", "")
        print(f"  Google API key found: {google_key[:20]}...")
    except Exception as e:
        print(f"  Could not read auth.json: {e}")
        google_key = ""
    endpoint = "https://daily-cloudcode-pa.googleapis.com"
    paths = ["/", "/v1/models", "/v1/chat/completions"]
    for path in paths:
        try:
            r = requests.get(
                f"{endpoint}{path}",
                headers={"Authorization": f"Bearer {google_key}"},
                timeout=10
            )
            print(f"  GET {path} -> {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"  GET {path} failed: {e}")
if __name__ == "__main__":
    print("Antigravity Integration Probe")
    print(f"CLI path: {ANTIGRAVITY_CLI}")
    print(f"CLI exists: {os.path.exists(ANTIGRAVITY_CLI)}")
    probe_cli()
    probe_ports()
    probe_extension_server()
    probe_cloud_endpoint()
    banner("SUMMARY")
    print("""
    Based on the probe results, determine which approach to use:
    APPROACH A: CLI Wrapper Proxy (if antigravity chat returns stdout)
      - Build a Python HTTP server that wraps 'antigravity chat' CLI calls
      - Expose as OpenAI-compatible /v1/chat/completions endpoint
      - Configure OpenCode to point to this local proxy
    APPROACH B: Extension Server Direct (if CSRF-authenticated requests work)
      - Communicate directly with the language server's extension endpoint
      - Requires extracting CSRF tokens from running processes
      - More fragile but lower latency
    APPROACH C: Cloud Code Endpoint (if the Google API key works)
      - Hit daily-cloudcode-pa.googleapis.com directly
      - Requires proper Google auth (may need OAuth, not API key)
      - Most direct but may not be possible without internal auth
    APPROACH D: MCP Bridge (if only MCP is available)
      - Use the MCP protocol to communicate with Antigravity
      - Would need an MCP-to-OpenAI adapter
      - Only useful for tool calls, not direct LLM chat
    """)
```
### Phase 2: OpenAI-Compatible Proxy Server
**File**: `antigravity_proxy.py`
**Purpose**: Based on Phase 1 results, build a proxy that exposes Claude Opus 4.6 as an OpenAI-compatible endpoint.
> **Note to build agent**: The best approach depends on Phase 1 probe results. Below is the **CLI Wrapper** approach (Approach A), which is the most likely to work since `antigravity chat` is a known working CLI. Adapt if probing reveals a better path.
```python
#!/usr/bin/env python3
"""
Antigravity → OpenAI-compatible proxy server.
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
import threading
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional
ANTIGRAVITY_CLI = os.path.expanduser("~/.antigravity/antigravity/bin/antigravity")
DEFAULT_PORT = 8462
MODEL_NAME = "claude-opus-4-6"
class AntigravityProxy(BaseHTTPRequestHandler):
    """HTTP handler that translates OpenAI API calls to antigravity chat CLI."""
    def do_GET(self):
        """Handle GET requests — models endpoint."""
        if self.path == "/v1/models":
            self._respond_json(200, {
                "object": "list",
                "data": [
                    {
                        "id": MODEL_NAME,
                        "object": "model",
                        "created": int(time.time()),
                        "owned_by": "antigravity-google-ai-ultra",
                        "permission": [],
                        "root": MODEL_NAME,
                        "parent": None,
                    }
                ]
            })
        elif self.path == "/health":
            self._respond_json(200, {"status": "ok"})
        else:
            self._respond_json(404, {"error": "not found"})
    def do_POST(self):
        """Handle POST requests — chat completions."""
        if self.path != "/v1/chat/completions":
            self._respond_json(404, {"error": "not found"})
            return
        # Parse request body
        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length))
        messages = body.get("messages", [])
        stream = body.get("stream", False)
        # Build the prompt from messages
        prompt = self._messages_to_prompt(messages)
        if stream:
            self._handle_streaming(prompt, body)
        else:
            self._handle_sync(prompt, body)
    def _messages_to_prompt(self, messages: list) -> str:
        """Convert OpenAI messages format to a single prompt string."""
        # For simple cases, just use the last user message
        # For complex cases, format the full conversation
        parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if isinstance(content, list):
                # Handle content array (multimodal)
                content = " ".join(
                    part.get("text", "") for part in content
                    if part.get("type") == "text"
                )
            if role == "system":
                parts.append(f"[System instruction: {content}]")
            elif role == "user":
                parts.append(content)
            elif role == "assistant":
                parts.append(f"[Previous assistant response: {content}]")
        return "\n\n".join(parts)
    def _call_antigravity(self, prompt: str) -> str:
        """Call antigravity chat CLI and return the response."""
        cmd = [ANTIGRAVITY_CLI, "chat", "-m", "ask", prompt]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,  # 2 minute timeout
                env={**os.environ, "NO_COLOR": "1"}  # Disable color codes
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
            elif result.stderr.strip():
                return f"Error: {result.stderr.strip()}"
            else:
                return "Error: No output from antigravity chat"
        except subprocess.TimeoutExpired:
            return "Error: antigravity chat timed out after 120s"
        except Exception as e:
            return f"Error: {str(e)}"
    def _handle_sync(self, prompt: str, body: dict):
        """Handle non-streaming chat completion."""
        response_text = self._call_antigravity(prompt)
        self._respond_json(200, {
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": MODEL_NAME,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": response_text,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": len(prompt.split()),
                "completion_tokens": len(response_text.split()),
                "total_tokens": len(prompt.split()) + len(response_text.split()),
            }
        })
    def _handle_streaming(self, prompt: str, body: dict):
        """Handle streaming chat completion (SSE)."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        response_text = self._call_antigravity(prompt)
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        # Stream the response in chunks
        words = response_text.split(' ')
        for i, word in enumerate(words):
            chunk_text = word + (' ' if i < len(words) - 1 else '')
            chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": MODEL_NAME,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": chunk_text},
                        "finish_reason": None,
                    }
                ]
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
        # Send final chunk
        final_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": MODEL_NAME,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
        }
        self.wfile.write(f"data: {json.dumps(final_chunk)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
    def _respond_json(self, status: int, data: dict):
        """Send a JSON response."""
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, format, *args):
        """Custom logging."""
        print(f"[{time.strftime('%H:%M:%S')}] {args[0]}")
def main():
    parser = argparse.ArgumentParser(description="Antigravity → OpenAI proxy")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    # Verify antigravity CLI exists
    if not os.path.exists(ANTIGRAVITY_CLI):
        print(f"ERROR: Antigravity CLI not found at {ANTIGRAVITY_CLI}")
        sys.exit(1)
    server = HTTPServer(("localhost", args.port), AntigravityProxy)
    print(f"Antigravity proxy listening on http://localhost:{args.port}")
    print(f"  /v1/models          - List available models")
    print(f"  /v1/chat/completions - Chat completions (sync + streaming)")
    print(f"\nUsing CLI: {ANTIGRAVITY_CLI}")
    print(f"Model: {MODEL_NAME}")
    print(f"\nOpenCode config for ~/.opencode.json:")
    print(json.dumps({
        "provider": {
            "antigravity": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Antigravity (Claude Opus 4.6)",
                "options": {
                    "baseURL": f"http://localhost:{args.port}/v1",
                    "apiKey": "not-needed"
                },
                "models": {
                    MODEL_NAME: {
                        "name": "Claude Opus 4.6 (via Antigravity)"
                    }
                }
            }
        }
    }, indent=2))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()
if __name__ == "__main__":
    main()
```
### Phase 3: OpenCode Configuration
**File**: `~/.opencode.json`
After the proxy is running, update OpenCode config:
```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "antigravity": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Antigravity (Claude Opus 4.6 via Google AI Ultra)",
      "options": {
        "baseURL": "http://localhost:8462/v1",
        "apiKey": "not-needed"
      },
      "models": {
        "claude-opus-4-6": {
          "name": "Claude Opus 4.6 (via Antigravity / Google AI Ultra)"
        }
      }
    },
    "ollama": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Ollama (local)",
      "options": {
        "baseURL": "http://localhost:11434/v1"
      },
      "models": {
        "llama3.2": { "name": "Llama 3.2" },
        "deepseek-r1": { "name": "DeepSeek R1" },
        "qwen2.5-coder": { "name": "Qwen 2.5 Coder" }
      }
    }
  },
  "agents": {
    "coder": {
      "model": "antigravity.claude-opus-4-6",
      "maxTokens": 16000
    },
    "task": {
      "model": "antigravity.claude-opus-4-6",
      "maxTokens": 16000
    },
    "title": {
      "model": "antigravity.claude-opus-4-6",
      "maxTokens": 80
    }
  },
  "autoCompact": true
}
```
---
## Build Agent Instructions (Step by Step)
### Prerequisites
- macOS with Antigravity app installed at `/Applications/Antigravity.app`
- Antigravity CLI at `~/.antigravity/antigravity/bin/antigravity`
- OpenCode installed at `~/.opencode/bin/opencode` (v1.2.15+)
- Python 3.10+ with `requests` library
- User is signed into Antigravity with Google AI Ultra subscription
### Step 1: Run the probe script
```bash
cd /Users/bedwards/.gemini/antigravity/playground/ultraviolet-eclipse
pip3 install requests
python3 probe_antigravity.py 2>&1 | tee probe_results.txt
```
**Analyze the output** to determine:
1. **Does `antigravity chat -m ask "prompt"` return output to stdout?**
   - If YES → Approach A (CLI Wrapper Proxy) will work. Proceed to Step 2.
   - If NO (it opens GUI instead) → the CLI is GUI-only. Try Approach B or C.
2. **Are there any undiscovered OpenAI-compatible endpoints on other ports?**
   - If YES → skip the proxy and point OpenCode directly at that port.
3. **Does the cloud code endpoint accept requests with the Google API key?**
   - If YES → build a simpler proxy that just forwards requests to Google's endpoint.
### Step 2: Build and test the proxy
Based on probe results, either use the CLI wrapper (`antigravity_proxy.py`) as-is, or adapt it:
```bash
# Start the proxy
python3 antigravity_proxy.py --port 8462 &
# Test it
curl http://localhost:8462/v1/models
curl -X POST http://localhost:8462/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-opus-4-6",
    "messages": [{"role": "user", "content": "Say hello in 5 words"}],
    "stream": false
  }'
```
### Step 3: Configure OpenCode
Update `~/.opencode.json` with the config from Phase 3 above.
### Step 4: Test the full pipeline
```bash
cd /Users/bedwards/.gemini/antigravity/playground/ultraviolet-eclipse
opencode
# Inside OpenCode, run /models and verify "Claude Opus 4.6 (via Antigravity)" appears
# Send a test message
```
### Known Risks & Edge Cases
| Risk | Mitigation |
|------|-----------|
| `antigravity chat` opens GUI window instead of returning stdout | Check if `--wait` flag or headless mode exists. May need to intercept the language_server directly. |
| CSRF tokens rotate on restart | Probe script re-reads them from process list each time |
| Proxy latency from CLI subprocess overhead | Consider persistent connection to language_server instead |
| Streaming not truly streaming (CLI returns all at once) | Acceptable for v1; can improve later with direct endpoint |
| Antigravity not running when proxy called | Proxy should return clear error; add health check |
| Port numbers change on Antigravity restart | Ports are dynamically assigned — probe script handles this |
### Alternative Approaches (if CLI wrapper fails)
**Approach B: Direct Extension Server**
- Extract CSRF token and extension server port from `ps aux`
- Send authenticated requests directly to the language server
- Requires reverse-engineering the internal API protocol
**Approach C: Google Cloud Code Endpoint**
- Extract OAuth token from Antigravity's internal auth state
- Call `daily-cloudcode-pa.googleapis.com` directly
- Look in `~/Library/Application Support/Antigravity/` for stored tokens
**Approach D: Use Gemini CLI as fallback**
- If Claude through Antigravity proves impossible to proxy, fall back to Gemini CLI
- `gemini` CLI supports Google AI Ultra via OAuth login
- Only provides Gemini models (not Claude) but still leverages the subscription
