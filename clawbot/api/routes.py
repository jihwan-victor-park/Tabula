from __future__ import annotations

from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs, urlparse

from clawbot.agents.messaging_agent import send_imessage
from clawbot.agents.price_discovery_agent import PriceDiscoveryAgent


JsonDict = dict[str, Any]


class ApiRoutes:
    def __init__(self, agent: PriceDiscoveryAgent | None = None) -> None:
        self.agent = agent or PriceDiscoveryAgent()

    def handle(
        self,
        method: str,
        path: str,
        body: JsonDict | None = None,
    ) -> tuple[int, JsonDict]:
        parsed = urlparse(path)

        # ------------------------------------------------------------------
        # POST routes
        # ------------------------------------------------------------------
        if method == "POST":
            if parsed.path == "/message/send":
                if not body or "recipient" not in body or "message" not in body:
                    return HTTPStatus.BAD_REQUEST, {
                        "error": "Both 'recipient' and 'message' fields are required."
                    }
                sent, error = send_imessage(body["recipient"], body["message"])
                return HTTPStatus.OK, {"sent": sent, "error": error}
            return HTTPStatus.NOT_FOUND, {"error": f"Unknown POST route: {parsed.path}"}

        # ------------------------------------------------------------------
        # GET routes
        # ------------------------------------------------------------------
        if method != "GET":
            return HTTPStatus.METHOD_NOT_ALLOWED, {"error": "Method not allowed."}

        if parsed.path == "/health":
            return HTTPStatus.OK, {"ok": True}
        if parsed.path == "/watchlist":
            return HTTPStatus.OK, self.agent.list_watch()
        if parsed.path == "/findings":
            return HTTPStatus.OK, self.agent.list_findings()
        if parsed.path == "/alerts":
            query = parse_qs(parsed.query)
            status = query.get("status", [None])[0]
            return HTTPStatus.OK, self.agent.list_alerts(status=status)
        if parsed.path == "/summary":
            return HTTPStatus.OK, self.agent.summary()

        return HTTPStatus.NOT_FOUND, {"error": f"Unknown route: {parsed.path}"}
