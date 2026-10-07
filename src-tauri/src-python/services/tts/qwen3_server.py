"""A tiny HTTP server around Qwen3-TTS 0.6B Base (the "balanced" narration voice, clones a recording), run by its own venv's Python
(bin/Qwen3-TTS/.venv).

    python qwen3_server.py --host 127.0.0.1 --port 8090 --idle-seconds 600

GET /health -> 200 once the model is loaded.
POST /v1/audio/speech {"input": text, "ref_audio": "<path to the reference recording>"} -> a mono WAV.

Imports only what that venv has (no Navivi code). The model is loaded once and the server exits by itself after --idle-seconds without a request.

Qwen3-TTS sometimes stops a line too early (the last syllable is cut off, depending on its random seed). A clip that ends while it is still loud
is therefore made again with another seed, up to MAX_ATTEMPTS, and the quietest ending is kept."""

import argparse
import io
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
LANGUAGE = "Japanese"
LOAD_WAIT_SECONDS = 300  # how long a request waits for the model before giving up
MAX_ATTEMPTS = 3
TAIL_SECONDS = 0.08  # the end of the clip that is checked
TAIL_OK = 0.15  # its energy against the whole clip's: measured 0.00-0.12 for lines that end properly, 0.19-0.31 for cut-off ones
END_PAUSE_SECONDS = 0.25  # silence after every line so a clip never ends on a click
REF_MAX_SECONDS = 15  # how much of the reference recording is used
ADD_FULL_STOP = True  # end a line without final punctuation with "。"
LINE_ENDS = "。！？!?」』）)…．."

_model = None
_prompts = {}
_ready = threading.Event()
_synth_lock = threading.Lock()
_last_request = time.monotonic()


_device = "cpu"


def _load(device: str):
    global _model, _device
    import torch
    from qwen_tts import Qwen3TTSModel

    if device == "cuda":
        torch.cuda.set_per_process_memory_fraction(float(os.environ.get("QWEN3_VRAM_FRACTION") or 0.4))
        _model = Qwen3TTSModel.from_pretrained(MODEL_ID, device_map="cuda:0", dtype=torch.bfloat16)
    else:
        _model = Qwen3TTSModel.from_pretrained(MODEL_ID, device_map="cpu", dtype=torch.float32)
    _device = device
    _prompts.clear()
    print("Qwen3-TTS model on %s" % device, flush=True)


def load_model():
    import torch

    torch.set_num_threads(int(os.environ.get("QWEN3_THREADS") or max(2, (os.cpu_count() or 8) // 2)))
    wanted = os.environ.get("QWEN3_DEVICE") or "cpu"
    if wanted == "cuda" and not torch.cuda.is_available():
        print("CUDA is not available to this torch build, using the CPU", flush=True)
        wanted = "cpu"
    try:
        _load(wanted)
    except Exception as exc:
        if wanted == "cpu":
            raise
        print("Loading on the GPU failed (%s), using the CPU" % exc, flush=True)
        _load("cpu")
    _ready.set()


def _fall_back_to_cpu(exc: Exception) -> None:
    import torch

    print("GPU synthesis failed (%s), moving to the CPU for the rest of this run" % exc, flush=True)
    global _model
    _model = None
    torch.cuda.empty_cache()
    _load("cpu")


def reference_audio(ref_audio: str):
    """The recording, cut to its first REF_MAX_SECONDS: the speaker's voice is the same and a long file only makes the analysis slow.
    A format soundfile cannot read is handed over as it is."""
    try:
        import soundfile as sf

        data, sample_rate = sf.read(ref_audio, dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        return (data[: int(sample_rate * REF_MAX_SECONDS)], sample_rate)
    except Exception:
        return ref_audio


def clone_prompt(ref_audio: str):
    key = (ref_audio, os.path.getmtime(ref_audio))
    if key not in _prompts:
        # No transcript of the recording is needed in this mode; it takes the speaker's voice only.
        _prompts[key] = _model.create_voice_clone_prompt(ref_audio=reference_audio(ref_audio), ref_text=None, x_vector_only_mode=True)
    return _prompts[key]


def tail_ratio(audio, sample_rate: int) -> float:
    import numpy as np

    n = max(1, int(sample_rate * TAIL_SECONDS))
    body = float(np.sqrt(np.mean(audio ** 2))) or 1e-9
    return float(np.sqrt(np.mean(audio[-n:] ** 2))) / body


def synthesize(text: str, ref_audio: str) -> bytes:
    import numpy as np
    import soundfile as sf
    import torch

    spoken = text + "。" if ADD_FULL_STOP and text and text[-1] not in LINE_ENDS else text

    def takes():
        best = None
        prompt = clone_prompt(ref_audio)
        base_seed = int(time.time()) % 100000
        for attempt in range(MAX_ATTEMPTS):
            torch.manual_seed(base_seed + attempt)
            wavs, sample_rate = _model.generate_voice_clone(
                text=spoken, language=LANGUAGE, voice_clone_prompt=prompt, max_new_tokens=len(spoken) * 4 + 40
            )
            audio = np.asarray(wavs[0], dtype=np.float32)
            ratio = tail_ratio(audio, sample_rate)
            if best is None or ratio < best[0]:
                best = (ratio, audio, sample_rate)
            if ratio <= TAIL_OK:
                break
            print("attempt %d ended while still loud (%.2f), trying another take" % (attempt + 1, ratio), flush=True)
        return best

    with _synth_lock:
        try:
            best = takes()
        except Exception as exc:
            if _device != "cuda":
                raise
            _fall_back_to_cpu(exc)
            best = takes()
        finally:
            if _device == "cuda":
                torch.cuda.empty_cache()
    _, audio, sample_rate = best
    audio = np.concatenate([audio, np.zeros(int(sample_rate * END_PAUSE_SECONDS), dtype=np.float32)])
    out = io.BytesIO()
    sf.write(out, audio, sample_rate, format="WAV", subtype="PCM_16")
    return out.getvalue()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
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
            ref_audio = str(body.get("ref_audio") or "")
            if not text:
                raise ValueError("'input' is empty.")
            if not os.path.isfile(ref_audio):
                raise FileNotFoundError("The reference recording was not found: %s" % ref_audio)
            self._reply(200, synthesize(text, ref_audio), "audio/wav")
        except Exception as exc:
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
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--idle-seconds", type=float, default=600)
    args = parser.parse_args()
    threading.Thread(target=load_model, daemon=True).start()
    threading.Thread(target=stop_when_idle, args=(args.idle_seconds,), daemon=True).start()
    print("Qwen3-TTS server on %s:%d" % (args.host, args.port), flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
