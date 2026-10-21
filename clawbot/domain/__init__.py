"""
Domain services. Every external write (web UI, MCP tools, batch workers) goes
through these functions so that tenant scope, idempotency and audit rules are
enforced in one place. Callers own the transaction (pass an open Session).
"""
