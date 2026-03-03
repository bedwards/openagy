# Openagy Project Memory

## Architecture
- **Goal**: Expose Antigravity's Claude Opus 4.6 as OpenAI-compatible API for OpenCode
- **Approach**: Python HTTP proxy wrapping `antigravity chat` CLI
- **Port**: 8462 (default)
- **Model ID**: `claude-opus-4-6`

## System Facts (probed 2026-03-02)
- Antigravity CLI v1.107.0 at `~/.antigravity/antigravity/bin/antigravity`
- `antigravity chat -m ask/edit/agent` opens GUI window (no headless mode)
- 4x `language_server_macos_x64` processes with CSRF tokens on dynamic ports
- Extension server validates CSRF tokens (returns "Invalid CSRF token")
- Language server port 53704 requires HTTPS; port 53705 returns 404
- Cloud endpoint: `https://daily-cloudcode-pa.googleapis.com`
- OpenCode v1.2.15 at `~/.opencode/bin/opencode`
- Python 3.13.9, requests 2.32.5
- Gemini CLI at `~/.nvm/versions/node/v22.22.0/bin/gemini`
- `gh` CLI v2.87.3

## OpenCode Config
- Existing: `~/.opencode.json` with Ollama provider (llama3.2, deepseek-r1, qwen2.5-coder)
- Agents currently pointing to `claude-4-opus` (needs fixing to `antigravity.claude-opus-4-6`)

## GitHub
- Repo: `git@github.com:bedwards/openagy.git`
- Gemini Code Assist: installed, "All repositories", no API key needed
- Workflow: feature branches → PRs → Gemini review → merge

## Development Workflow (STRICT)
1. **Feature branches** for all changes (never commit directly to main)
2. **Gemini Code Assist reviews** every PR — react to ALL feedback before merge
3. **PR checks MUST be green** before merge — no exceptions
4. **Main branch MUST stay green** after every merge
5. **Frequent commits** with descriptive messages
6. **Unit tests** required — CI runs pytest + linting on every PR
7. **Squash-merge** PRs for clean history

## Integration Approaches (priority order)
1. **Approach A**: CLI wrapper proxy (most reliable, `antigravity chat` is documented)
2. **Approach B**: Direct extension server (fragile, CSRF token rotation)
3. **Approach C**: Cloud code endpoint (needs OAuth from Antigravity's internal auth)
4. **Approach D**: Gemini CLI fallback (only Gemini models, not Claude)
