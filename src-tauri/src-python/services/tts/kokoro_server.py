"""A tiny HTTP server around Kokoro (the fast narration voice), run by the Kokoro venv's own Python (bin/Kokoro-TTS/.venv).

    python kokoro_server.py --host 127.0.0.1 --port 8089 --idle-seconds 600

GET /health -> 200 once the model is loaded.
POST /v1/audio/speech {"input": text, "voice": "jf_tebukuro", "speed": 1.0} -> a 24 kHz mono WAV.

Imports only what the Kokoro venv has (no Navivi code). The model is loaded once; the server exits by itself after --idle-seconds
without a request, so nothing keeps holding memory after a run."""

import argparse
import io
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SAMPLE_RATE = 24000
LANG_CODE = "j"  # Japanese
REPO_ID = "hexgrad/Kokoro-82M"
LOAD_WAIT_SECONDS = 300  # how long a request waits for the model before giving up

_pipeline = None
_ready = threading.Event()
_synth_lock = threading.Lock()
_last_request = time.monotonic()


def load_pipeline():
    global _pipeline
    from kokoro import KPipeline

    _pipeline = KPipeline(lang_code=LANG_CODE, repo_id=REPO_ID)
    _ready.set()


def synthesize(text: str, voice: str, speed: float) -> bytes:
    import numpy as np
    import soundfile as sf

    with _synth_lock:
        chunks = [np.asarray(audio, dtype=np.float32) for _, _, audio in _pipeline(text, voice=voice, speed=speed)]
    if not chunks:
        raise ValueError("Kokoro returned no audio for this text.")
    out = io.BytesIO()
    sf.write(out, np.concatenate(chunks), SAMPLE_RATE, format="WAV", subtype="PCM_16")
    return out.getvalue()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # one short line per request on stderr (the server log)
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def _reply(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/health":
            return self._reply(404, b"{}", "application/json")
        if _ready.is_set():
            self._reply(200, b'{"status":"ok"}', "application/json")
        else:
            self._reply(503, b'{"status":"loading"}', "application/json")

    def do_POST(self):
        global _last_request
        _last_request = time.monotonic()
        if self.path != "/v1/audio/speech":
            return self._reply(404, b"{}", "application/json")
        # The port is open while the model is still loading; a request that arrives then waits for it instead of failing.
        if not _ready.wait(LOAD_WAIT_SECONDS):
            return self._reply(503, b'{"error":"The model did not finish loading."}', "application/json")
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            text = str(body.get("input") or "").strip()
            if not text:
                raise ValueError("'input' is empty.")
            audio = synthesize(text, str(body.get("voice") or "jf_tebukuro"), float(body.get("speed") or 1.0))
            self._reply(200, audio, "audio/wav")
        except Exception as exc:  # the client shows this text
            self._reply(500, json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode("utf-8"), "application/json")
        finally:
            _last_request = time.monotonic()


def stop_when_idle(seconds: float) -> None:
    while True:
        time.sleep(15)
        if time.monotonic() - _last_request > seconds:
            print("Idle for %.0f s, stopping." % seconds, flush=True)
            os._exit(0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8089)
    parser.add_argument("--idle-seconds", type=float, default=600)
    args = parser.parse_args()
    threading.Thread(target=load_pipeline, daemon=True).start()
    threading.Thread(target=stop_when_idle, args=(args.idle_seconds,), daemon=True).start()
    print("Kokoro server on %s:%d" % (args.host, args.port), flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
