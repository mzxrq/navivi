"""Local HTTP server used to serve local 3D assets safely to Playwright."""

import http.server
import os
import socketserver
import threading
import urllib.parse


class ThreadedHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


def start_local_server(directory, assets_dir=None):
    """Starts a background web server to serve local 3D assets safely to
    Playwright.

    `directory` (usually the render's own project/config folder) is served
    at '/'. `assets_dir` (the app's bundled .glb models etc., usually a
    different tree than `directory` — e.g. the project lives under the
    user's Documents while the app's assets live under its own install/
    source dir) is served at '/assets/'. Python's http.server refuses to
    walk '..' out of its document root, so without this split a caller
    can't reach both trees through relative paths from a single root.
    """
    assets_root = os.path.join(assets_dir, "assets") if assets_dir else None

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)

        def translate_path(self, path):
            if assets_root and (path == "/assets" or path.startswith("/assets/")):
                rel = urllib.parse.unquote(path[len("/assets/"):] if path.startswith("/assets/") else "")
                rel = rel.split("?", 1)[0].split("#", 1)[0]
                return os.path.join(assets_root, *rel.split("/")) if rel else assets_root
            return super().translate_path(path)

        def log_message(self, format, *args):
            pass

    server = ThreadedHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port
