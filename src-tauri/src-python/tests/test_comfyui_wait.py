"""Waiting on a ComfyUI job: a long job keeps the server alive, a server that died ends the wait early."""

import httpx
import pytest

from services.vdoprocessing import comfyui_i2v_client as client_mod
from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient


@pytest.fixture
def comfy(monkeypatch, tmp_path):
    c = ComfyUII2VClient.__new__(ComfyUII2VClient)
    c.base_url = "http://127.0.0.1:1"
    c.touched = 0
    monkeypatch.setattr(ComfyUII2VClient, "_touch_activity", lambda self: setattr(self, "touched", self.touched + 1))
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(ComfyUII2VClient, "_SERVER_DIR", tmp_path)
    return c


class _Http:
    def __init__(self, replies):
        self.replies = iter(replies)

    def get(self, url, timeout=None):
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return httpx.Response(200, json=reply, request=httpx.Request("GET", url))


def test_every_poll_of_a_running_job_counts_as_activity(comfy):
    done = {"p": {"status": {}, "outputs": {"9": {"videos": ["v"]}}}}
    out = comfy._wait_for_result(_Http([{}, {}, {}, done]), "p", output_node="9", timeout=60)
    assert out == {"videos": ["v"]} and comfy.touched == 4


def test_a_server_that_stopped_answering_ends_the_wait(comfy, monkeypatch):
    clock = iter(range(0, 10_000, 30))
    monkeypatch.setattr(client_mod.time, "monotonic", lambda: next(clock))
    refused = httpx.ConnectError("refused")
    with pytest.raises(RuntimeError, match="stopped"):
        comfy._wait_for_result(_Http([refused] * 100), "p", timeout=1200)
