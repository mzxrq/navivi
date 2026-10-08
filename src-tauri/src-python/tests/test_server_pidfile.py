"""The pidfile a spawning process leaves behind: believed only while its PID really is our server, never trusted when stale.

Windows hands PIDs out again quickly and a crash leaves the file, so a live PID that is some other program must not block a start;
and when another process's server dies while loading, the waiting process must stop waiting at once."""

import asyncio

import pytest

from services.tts.ttsengine import IrodoriTTSClient, KokoroTTSClient, Qwen3TTSClient
from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient

CLIENTS = [IrodoriTTSClient, KokoroTTSClient, Qwen3TTSClient, ComfyUII2VClient]


@pytest.fixture(params=CLIENTS, ids=lambda c: c.__name__)
def client(request, tmp_path, monkeypatch):
    cls = request.param
    monkeypatch.setattr(cls, "_PIDFILE", tmp_path / ".server.pid")
    return cls


def write_pid(cls, pid=4242):
    cls._PIDFILE.write_text(str(pid))


def test_no_pidfile_means_nobody_is_starting_it(client):
    assert client._other_process_is_starting_server() is False


def test_a_dead_pid_means_nobody_is_starting_it(client, monkeypatch):
    write_pid(client)
    monkeypatch.setattr(client, "_pid_is_alive", staticmethod(lambda pid: False))
    assert client._other_process_is_starting_server() is False


def test_a_live_pid_running_our_server_is_believed(client, monkeypatch):
    write_pid(client)
    monkeypatch.setattr(client, "_pid_is_alive", staticmethod(lambda pid: True))
    monkeypatch.setattr(client, "_pid_command_line", staticmethod(lambda pid: f"python.exe {client._PROCESS_MARKER} --port 1"))
    assert client._other_process_is_starting_server() is True
    assert client._PIDFILE.exists()


def test_a_live_pid_that_is_another_program_is_a_stale_file(client, monkeypatch):
    write_pid(client)
    monkeypatch.setattr(client, "_pid_is_alive", staticmethod(lambda pid: True))
    monkeypatch.setattr(client, "_pid_command_line", staticmethod(lambda pid: "notepad.exe C:\\notes.txt"))
    assert client._other_process_is_starting_server() is False, "the PID was reused: start our own server"
    assert not client._PIDFILE.exists(), "the stale file is removed"


def test_an_unreadable_command_line_is_trusted_rather_than_starting_a_second_copy(client, monkeypatch):
    write_pid(client)
    monkeypatch.setattr(client, "_pid_is_alive", staticmethod(lambda pid: True))
    monkeypatch.setattr(client, "_pid_command_line", staticmethod(lambda pid: None))
    assert client._other_process_is_starting_server() is True
    assert client._PIDFILE.exists()


@pytest.mark.parametrize("cls", [IrodoriTTSClient, KokoroTTSClient, Qwen3TTSClient])
def test_waiting_on_another_process_stops_as_soon_as_its_server_dies(cls, tmp_path, monkeypatch):
    fake_python = tmp_path / "python.exe"
    fake_python.write_text("")
    monkeypatch.setattr(cls, "_PIDFILE", tmp_path / ".server.pid")
    monkeypatch.setattr(cls, "_SERVER_VENV_PYTHON", fake_python)
    monkeypatch.setattr(cls, "_server_process", None)
    monkeypatch.setattr(cls, "_SERVER_START_TIMEOUT_SECONDS", 600.0)

    async def never_up(self):
        return False

    monkeypatch.setattr(cls, "_is_server_up", never_up)
    write_pid(cls)
    answers = iter([True])  # alive when the start is decided, gone by the first poll
    monkeypatch.setattr(cls, "_pid_is_alive", staticmethod(lambda pid: next(answers, False)))
    monkeypatch.setattr(cls, "_pid_command_line", staticmethod(lambda pid: None))

    with pytest.raises(RuntimeError, match="stopped before it was ready"):
        asyncio.run(cls(output_dir=tmp_path / "out")._ensure_server_running())


def test_comfyui_stops_waiting_when_the_other_servers_pid_is_gone(tmp_path, monkeypatch):
    cls = ComfyUII2VClient
    fake_python = tmp_path / "python.exe"
    fake_python.write_text("")
    monkeypatch.setattr(cls, "_PIDFILE", tmp_path / ".server.pid")
    monkeypatch.setattr(cls, "_SERVER_VENV_PYTHON", fake_python)
    monkeypatch.setattr(cls, "_server_process", None)
    monkeypatch.setattr(cls, "_is_server_up", lambda self: False)
    write_pid(cls)
    answers = iter([True])
    monkeypatch.setattr(cls, "_pid_is_alive", staticmethod(lambda pid: next(answers, False)))
    monkeypatch.setattr(cls, "_pid_command_line", staticmethod(lambda pid: None))
    with pytest.raises(RuntimeError, match="stopped before it was ready"):
        cls()._ensure_server_running()
