"""ComfyUI's server log is tailed into the CLI: sampler progress and phases
on the status line, warnings/errors/tracebacks as persistent notes."""

import pytest

from services.vdoprocessing import comfyui_i2v_client as client


def _append(path, data: bytes):
    with open(path, "ab") as f:
        f.write(data)


def test_tail_returns_only_new_complete_lines(tmp_path):
    log = tmp_path / "server.log"
    log.write_bytes(b"old line before the job\n")
    tail = client._ServerLogTail(log)

    _append(log, b"\x1b[32m[INFO]\x1b[0m Requested to load WAN22\n  0%|  | 0/4 [00:00<?, ?it/s]\r 25%|\xe2\x96\x88 | 1/4 [00:21<01:05, 21.77s/it]\r 50%|")
    assert [l.strip() for l in tail.poll()] == [
        "[INFO] Requested to load WAN22",
        "0%|  | 0/4 [00:00<?, ?it/s]",
        "25%|█ | 1/4 [00:21<01:05, 21.77s/it]",
    ]
    assert tail.poll() == []

    _append(log, b"\xe2\x96\x88\xe2\x96\x88 | 2/4 [00:40<00:40, 20.13s/it]\n")
    assert [l.strip() for l in tail.poll()] == ["50%|██ | 2/4 [00:40<00:40, 20.13s/it]"]


def test_tail_of_missing_file_is_empty(tmp_path):
    assert client._ServerLogTail(tmp_path / "nope.log").poll() == []


@pytest.fixture
def calls(monkeypatch):
    seen = []
    monkeypatch.setattr(client.tracker, "show", lambda text: seen.append(("show", text)))
    monkeypatch.setattr(client.tracker, "note", lambda text: seen.append(("note", text)))
    return seen


def test_progress_and_phases_go_to_the_status_line(calls):
    reporter = client._ServerLogReporter("Wan segment 2/6")
    reporter.report([
        "[INFO] Using MixedPrecisionOps for text encoder",
        "[INFO] Requested to load WAN22",
        " 50%|██ | 2/4 [00:40<00:40, 20.13s/it]",
        " 50%|██ | 2/4 [00:40<00:40, 20.13s/it]",
        "100%|████| 4/4 [01:20<00:00, 20.17s/it]",
        "[INFO] Requested to load WanVAE",
    ])
    assert calls == [
        ("show", "Wan segment 2/6 · loading model"),
        ("show", "Wan segment 2/6 · step 2/4 · ETA 00:40"),
        ("show", "Wan segment 2/6 · step 4/4"),
        ("show", "Wan segment 2/6 · VAE decode"),
    ]


def test_warnings_and_tracebacks_become_notes(calls):
    client._ServerLogReporter("Wan").report([
        "[WARNING] something odd",
        "Traceback (most recent call last):",
        '  File "execution.py", line 1, in run',
        "torch.OutOfMemoryError: CUDA out of memory",
        "[INFO] Prompt executed in 3.2 seconds",
    ])
    assert calls == [
        ("note", "[ComfyUI] [WARNING] something odd"),
        ("note", "[ComfyUI] Traceback (most recent call last):"),
        ("note", '[ComfyUI]   File "execution.py", line 1, in run'),
        ("note", "[ComfyUI] torch.OutOfMemoryError: CUDA out of memory"),
    ]
