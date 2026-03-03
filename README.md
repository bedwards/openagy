# Openagy

**Antigravity → OpenCode Integration**: Expose Claude Opus 4.6 (via Google AI Ultra subscription) as an OpenAI-compatible API for [OpenCode](https://opencode.ai/).

## Architecture

```
OpenCode CLI ──→ Antigravity Proxy (localhost:8462) ──→ antigravity chat CLI ──→ Google AI Ultra
                 /v1/chat/completions                   Claude Opus 4.6
```

## Quick Start

### 1. Run the probe (optional)
```bash
python3 probe_antigravity.py
```

### 2. Start the proxy
```bash
python3 antigravity_proxy.py --port 8462
```

### 3. Configure OpenCode
Add to `~/.opencode.json`:
```json
{
  "provider": {
    "antigravity": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Claude Opus 4.6 (via Antigravity / Google AI Ultra)",
      "options": {
        "baseURL": "http://localhost:8462/v1",
        "apiKey": "not-needed"
      },
      "models": {
        "claude-opus-4-6": {
          "name": "Claude Opus 4.6 (via Antigravity / Google AI Ultra)"
        }
      }
    }
  }
}
```

### 4. Test
```bash
curl http://localhost:8462/v1/models
curl http://localhost:8462/health
```

## Prerequisites

- macOS with [Antigravity](https://cloud.google.com/antigravity) installed
- Google AI Ultra subscription (signed in to Antigravity)
- Python 3.10+
- [OpenCode](https://opencode.ai/) v1.2.15+

## Code Review

This repo uses **Gemini Code Assist** for automated PR reviews via Google AI Ultra subscription.
