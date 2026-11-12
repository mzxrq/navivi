"""The renderer's local web server only hands out files from its two folders."""

import urllib.error
import urllib.request

from services.vdoprocessing.pydeckrecorder.httpserver import start_local_server


def test_assets_are_served_but_dot_dot_cannot_leave_the_folder(tmp_path):
    project, app = tmp_path / "project", tmp_path / "app"
    (app / "assets").mkdir(parents=True)
    project.mkdir()
    (app / "assets" / "model.glb").write_text("glb", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    server, port = start_local_server(str(project), str(app))
    try:
        base = f"http://127.0.0.1:{port}"
        assert urllib.request.urlopen(f"{base}/assets/model.glb").read() == b"glb"
        for path in ("/assets/../../secret.txt", "/assets/..%2F..%2Fsecret.txt", "/assets/..%5C..%5Csecret.txt"):
            try:
                body = urllib.request.urlopen(base + path).read()
            except urllib.error.HTTPError as exc:
                assert exc.code == 404
            else:
                assert b"secret" not in body
    finally:
        server.shutdown()
