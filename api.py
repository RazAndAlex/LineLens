"""LineLens — FastAPI + React entry point (the Streamlit app's successor).

Run locally:

    uv sync --extra web
    uv run python api.py

Serves the API under /api and, when the frontend build exists (web/dist), the
React app at /. Importing this module only *builds* the app object (for
uvicorn's ``api:app`` style); the server + browser launch live in main().
"""
from __future__ import annotations

import threading
import webbrowser
from pathlib import Path

_HOST = "127.0.0.1"
_PORT = 8741
_DIST = Path(__file__).resolve().parent / "web" / "dist"


def build_app():
    """The FastAPI app, with the built React frontend mounted at / when present."""
    from server.app import create_app

    app = create_app()

    @app.middleware("http")
    async def _no_cache_html(request, call_next):
        """HTML is always revalidated — hashed JS/CSS assets stay cacheable, but
        a stale cached index.html must never pin the user to an old build."""
        response = await call_next(request)
        ct = response.headers.get("content-type", "")
        # HTML always revalidates (a stale cached index.html must never pin the
        # user to an old build); the tab icon too — it is not content-hashed.
        if "text/html" in ct or request.url.path in ("/icon.svg", "/icon.png"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    if _DIST.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=_DIST, html=True), name="web")
    return app


app = build_app()


def main() -> None:
    import uvicorn

    url = f"http://{_HOST}:{_PORT}"
    print(f"Starting LineLens...  your browser will open at {url}")
    print("Close this window (or press Ctrl+C) to stop it.")
    # Open the browser once the server has had a moment to bind (the LineLens.bat
    # behavior: double-click -> browser opens; console-bound process).
    threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=_HOST, port=_PORT)


if __name__ == "__main__":
    main()
