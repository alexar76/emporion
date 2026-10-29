"""SYMMARTYS FastAPI app — oracle-core surface, provider signatures, health and an index."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from oracle_core import create_app

from symmartys import __version__
from symmartys.capabilities import Runtime, build_spec
from symmartys.middleware import ProviderSignatureMiddleware
from symmartys.config import setting


def build_app(runtime: Runtime | None = None, public_url: str | None = None) -> FastAPI:
    """The app. Background list refreshes are started by main(), never here, so tests and
    tools that build the app do not download 35 MB of sanctions lists."""
    runtime = runtime or Runtime()
    spec = build_spec(runtime, public_url)

    def extra(app: FastAPI, proto) -> None:
        app.state.runtime = runtime

        @app.get("/health")
        async def health() -> dict[str, Any]:
            lists = runtime.sanctions.status()["lists"]
            return {"status": "ok", "service": "symmartys", "version": __version__,
                    "capabilities": len(spec.capabilities),
                    "sanctions_lists_loaded": sorted(k for k, v in lists.items() if v)}

        @app.get("/")
        async def index() -> dict[str, Any]:
            return {
                "service": spec.name, "version": __version__,
                "manifest": f"{spec.public_url.rstrip('/')}/ai-market/v2/manifest",
                "invoke": f"{spec.public_url.rstrip('/')}/ai-market/v2/invoke",
                "capabilities": [{"id": c.capability_id, "price_usd": c.price_per_call_usd}
                                 for c in spec.capabilities],
                "docs": "https://modelmarket.dev/",
            }

    app = create_app(spec, cors_origins=setting("CORS_ORIGINS"),
                     invoke_rate_limit=int(setting("RATE_LIMIT", "120")),
                     extra=extra)
    app.add_middleware(ProviderSignatureMiddleware, signer=app.state.protocol.signer)
    # Timer deliveries are signed with the same key the manifest names.
    runtime.timers.signer = app.state.protocol.signer
    return app


__all__ = ["build_app"]
