# Architectural Decisions & Deviations Log (DECISIONS.md)

This document records key architectural decisions, package choices, substitutions, and resolution of constraints encountered during development.

---

## Decision Log

### ADR-001: Python Version Upgrade to 3.12.10
- **Context:** NFR-1.1 requires Python 3.11+. The system default was Python 3.9.0.
- **Decision:** Installed Python 3.12.10 via Windows Package Manager (`winget install Python.Python.3.12`).
- **Rationale:** Python 3.12 provides improved performance, modern typing support, and full compatibility with `mcp` and `google-genai` libraries.
- **Impact:** Virtual environment `.venv` is created with Python 3.12.10.

---

### ADR-002: Node.js Installation for Gemini CLI & Tooling
- **Context:** Gemini CLI (`@google/gemini-cli`) requires a Node.js runtime environment.
- **Decision:** Installed Node.js v24.19.0 LTS via `winget install OpenJS.NodeJS.LTS`.
- **Rationale:** Ensures clean subprocess invocation of `gemini` CLI commands on Windows without PATH ambiguities.
- **Impact:** Both Python and Node.js toolchains are available.

---

### ADR-003: COROS MCP Server Connection via HTTP Transport
- **Context:** COROS consolidated regional endpoints into `https://mcp.coros.com/mcp` using HTTP / SSE transport.
- **Decision:** Configured COROS MCP server using `http` transport with Bearer token / OAuth 2.0 authentication.
- **Rationale:** Matches official COROS MCP architecture specification.
- **Impact:** HTTP transport added to `gemini mcp` configuration and Python `mcp` client configuration.

---

### ADR-004: Subprocess Integration Pattern for Gemini CLI
- **Context:** NFR-1.3 requires Gemini CLI invoked as a subprocess with explicit timeouts, structured error handling, and retry-with-backoff.
- **Decision:** Built `GeminiCLIWrapper` in `app/llm/gemini_cli.py` with configurable timeouts and exponential backoff retry logic (up to 3 retries).
- **Rationale:** Prevents application hangs during LLM prompt generation while gracefully handling transient network delays.

---

### ADR-005: Fallback Mechanisms for COROS Metrics
- **Context:** FR-1.2 lists 23 distinct metrics. Some body metrics or raw sensor metrics may be missing for athletes without specific hardware (e.g. POD 2).
- **Decision:** Documented fallbacks in `COROS_CAPABILITIES.md`:
  - Grade-Adjusted Pace (GAP): Calculated via Minetti equation if raw GAP field absent.
  - VO2max: Calculated via Jack Daniels VDOT tables if Evolab metric unavailable.
  - TSS / Training Load: Derived using TRIMPS HR zone calculation if COROS load missing.
  - Weight & Body Metrics: Editable via profile form settings UI.
