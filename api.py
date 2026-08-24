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
    else:
        _mount_build_instructions(app)
    return app


# The launcher opens a browser as soon as the server binds. Without a frontend
# build there is nothing at /, and the visitor gets a bare {"detail":"Not
# Found"} with no way to know that one npm command fixes it. This page says so.
_NO_BUILD_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LineLens needs a frontend build</title>
<style>
  body { background:#0e1114; color:#e6eaee; margin:0; padding:48px 24px;
         font:16px/1.6 "Segoe UI", system-ui, sans-serif; }
  main { max-width: 640px; margin: 0 auto; }
  h1 { font-size: 24px; margin: 0 0 16px; }
  p { color:#8892a0; }
  pre { background:#161a1f; border:1px solid #262c33; padding:16px;
        overflow-x:auto; color:#e6eaee; }
  code { font-family: ui-monospace, Consolas, monospace; }
  a { color:#f0a63c; }
</style>
</head>
<body>
<main>
  <h1>LineLens needs a frontend build</h1>
  <p>The API is running. The user interface is not built yet, so there is
     nothing to show at this address.</p>
  <p>Node.js 20 or newer builds it. You need this one time.</p>
  <pre><code>npm --prefix web ci
npm --prefix web run build</code></pre>
  <p>Then restart LineLens and reload this page.</p>
  <p>The API works without the interface. Read
     <a href="/docs">/docs</a> for the endpoints.</p>
</main>
</body>
</html>
"""


def _mount_build_instructions(app) -> None:
    """Answer / with build instructions while web/dist is missing."""
    from fastapi.responses import HTMLResponse

    @app.get("/", include_in_schema=False)
    def _no_build() -> HTMLResponse:
        return HTMLResponse(_NO_BUILD_PAGE, status_code=503)


app = build_app()


def main() -> None:
    import uvicorn

    url = f"http://{_HOST}:{_PORT}"
    if not _DIST.is_dir():
        print("The frontend is not built yet. Build it once with:")
        print("    npm --prefix web ci")
        print("    npm --prefix web run build")
        print("Then restart LineLens. The API runs either way.")
        print()
    print(f"Starting LineLens...  your browser will open at {url}")
    print("Close this window (or press Ctrl+C) to stop it.")
    # Open the browser once the server has had a moment to bind (the LineLens.bat
    # behavior: double-click -> browser opens; console-bound process).
    threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=_HOST, port=_PORT)


if __name__ == "__main__":
    main()
