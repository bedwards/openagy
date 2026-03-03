# OpenAgy Code Style Guide

## Language & Runtime
- Python 3.10+ with type hints
- No external dependencies beyond stdlib where possible (`requests` is acceptable)
- Use `argparse` for CLI arguments

## Code Quality
- All functions must have docstrings
- Use `snake_case` for functions and variables
- Use `PascalCase` for classes
- Constants in `UPPER_SNAKE_CASE`
- Maximum line length: 100 characters
- Handle all exceptions explicitly — no bare `except:`

## Architecture
- OpenAI-compatible API format for all proxy endpoints
- JSON responses with proper HTTP status codes
- SSE streaming format for `/v1/chat/completions` with `stream: true`
- Health check endpoint at `/health`
- Structured logging with timestamps

## Security
- Never log API keys, tokens, or credentials
- CSRF tokens should be read dynamically, never hardcoded
- Proxy should only bind to localhost by default

## Testing
- All probe/discovery scripts must handle timeouts gracefully
- Error responses must include actionable messages
