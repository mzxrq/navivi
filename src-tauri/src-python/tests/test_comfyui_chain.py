"""Last-frame chaining (tuning.COMFYUI_CHAIN_LAST_FRAME): one ComfyUI job per
segment, each started from a PNG of the previous segment's last frame, the
segments joined with ffmpeg. No ComfyUI server and no ffmpeg run here - the
job and the join are stubbed, so what is checked is the wiring."""

import cv2
import numpy as np
import pytest

from services import tuning
from services.vdoprocessing import comfyui_i2v_client as client_mod
from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient

SEGMENT_SEC = tuning.COMFYUI_MAX_FRAMES / tuning.COMFYUI_GEN_FPS
LONG_ENOUGH = SEGMENT_SEC * 1.5  # needs more than one segment


def _write_video(path, colour, frames=3):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 24, (64, 64))
    for i in range(frames):
        frame = np.full((64, 64, 3), colour, dtype=np.uint8)
        frame[0, 0] = (i, i, i)  # so the frames differ
        writer.write(frame)
    writer.release()
    return path


def _write_photo(path, colour):
    cv2.imwrite(str(path), np.full((64, 64, 3), colour, dtype=np.uint8))
    return path


class _Recorder:
    """A client whose ComfyUI calls are recorded instead of made."""

    def __init__(self, tmp_path, segments=2):
        self.client = ComfyUII2VClient.__new__(ComfyUII2VClient)
        self.tmp_path = tmp_path
        self.uploaded = []
        self.graphs = []
        self.joined = None
        self.client._ensure_server_running = lambda: None
        self.client._upload_image = lambda _c, path: self.uploaded.append(path) or f"up{len(self.uploaded)}.png"
        self.client._run_segment = self._run_segment

    def _run_segment(self, _client, graph, output_path, _label="Wan"):
        self.graphs.append(graph)
        _write_video(output_path, 40 + 60 * len(self.graphs))
        return output_path


@pytest.fixture
def recorder(tmp_path, monkeypatch):
    monkeypatch.setattr(tuning, "COMFYUI_MODEL", "5b")
    monkeypatch.setattr(tuning, "COMFYUI_GEN_FPS", tuning.COMFYUI_FPS)
    monkeypatch.setattr(tuning, "COMFYUI_CHAIN_LAST_FRAME", True)
    monkeypatch.setattr(tuning, "COMFYUI_EXTEND_MAX_SEGMENTS", 2)
    monkeypatch.setattr(tuning, "COMFYUI_INPUT_EDGE_CROP", 0.0)
    rec = _Recorder(tmp_path)
    monkeypatch.setattr(client_mod, "_join_segments", lambda paths, out: setattr(rec, "joined", list(paths)) or out)
    return rec


class TestEdgeCrop:
    def test_trims_every_edge(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tuning, "COMFYUI_INPUT_EDGE_CROP", 0.05)
        photo = tmp_path / "photo.png"
        cv2.imwrite(str(photo), np.zeros((200, 400, 3), np.uint8))
        out = client_mod._edge_cropped(str(photo), str(tmp_path / "in.png"))
        assert cv2.imread(out).shape[:2] == (180, 360)

    def test_off_uses_the_photo_itself(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tuning, "COMFYUI_INPUT_EDGE_CROP", 0.0)
        assert client_mod._edge_cropped("photo.png", "in.png") == "photo.png"


class TestChainedGeneration:
    def test_every_segment_is_its_own_single_segment_job(self, recorder, tmp_path):
        photo = _write_photo(tmp_path / "photo.jpg", (120, 120, 120))
        recorder.client.generate_clip(str(photo), str(tmp_path / "out.mp4"), LONG_ENOUGH, "pan-right")

        assert len(recorder.graphs) == 2
        for graph in recorder.graphs:  # never the unrolled one-graph form
            assert not [k for k in graph if k.startswith("ext")]
        assert len(recorder.joined) == 2

    def test_the_next_segment_starts_from_the_previous_last_frame(self, recorder, tmp_path):
        photo = _write_photo(tmp_path / "photo.jpg", (120, 120, 120))
        recorder.client.generate_clip(str(photo), str(tmp_path / "out.mp4"), LONG_ENOUGH, "pan-right")

        assert recorder.uploaded[0] == str(photo)
        assert recorder.uploaded[1].endswith("frame0.png")  # not the photo again

    def test_one_segment_still_goes_through_a_single_graph(self, recorder, tmp_path):
        photo = _write_photo(tmp_path / "photo.jpg", (120, 120, 120))
        recorder.client.generate_clip(str(photo), str(tmp_path / "out.mp4"), 2.0, "pan-right")

        assert len(recorder.graphs) == 1 and recorder.joined is None
        assert recorder.uploaded == [str(photo)]

    def test_switched_off_it_falls_back_to_the_unrolled_graph(self, recorder, tmp_path, monkeypatch):
        monkeypatch.setattr(tuning, "COMFYUI_CHAIN_LAST_FRAME", False)
        photo = _write_photo(tmp_path / "photo.jpg", (120, 120, 120))
        recorder.client.generate_clip(str(photo), str(tmp_path / "out.mp4"), LONG_ENOUGH, "pan-right")

        assert len(recorder.graphs) == 1
        assert recorder.graphs[0]["ext1_last"]["inputs"]["batch_index"] == -1

    def test_the_working_folder_is_cleaned_up(self, recorder, tmp_path):
        photo = _write_photo(tmp_path / "photo.jpg", (120, 120, 120))
        recorder.client.generate_clip(str(photo), str(tmp_path / "out.mp4"), LONG_ENOUGH, "pan-right")

        assert not list(tmp_path.glob(".chain_*"))


class TestChainedFrame:
    def test_the_handed_on_frame_is_pulled_back_towards_the_photo(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tuning, "COMFYUI_CHAIN_COLOR_MATCH", True)
        photo = _write_photo(tmp_path / "photo.jpg", (110, 110, 110))
        video = _write_video(tmp_path / "seg.mp4", 210)  # Wan brightened it

        out = client_mod._write_last_frame(str(video), str(photo), str(tmp_path / "f.png"))
        handed_on = float(cv2.imread(out).mean())
        assert abs(handed_on - 110) < abs(210 - 110)

    def test_without_the_colour_pass_the_frame_is_handed_on_as_it_is(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tuning, "COMFYUI_CHAIN_COLOR_MATCH", False)
        photo = _write_photo(tmp_path / "photo.jpg", (110, 110, 110))
        video = _write_video(tmp_path / "seg.mp4", 210)

        out = client_mod._write_last_frame(str(video), str(photo), str(tmp_path / "f.png"))
        assert abs(float(cv2.imread(out).mean()) - 210) < 12  # the codec moves it a little

    def test_an_empty_clip_is_an_error_rather_than_a_silent_freeze(self, tmp_path):
        photo = _write_photo(tmp_path / "photo.jpg", (110, 110, 110))
        empty = tmp_path / "empty.mp4"
        empty.write_bytes(b"")
        with pytest.raises(RuntimeError):
            client_mod._write_last_frame(str(empty), str(photo), str(tmp_path / "f.png"))


class TestGenerationFps:
    def test_a_lower_generation_rate_is_resampled_even_for_one_segment(self, recorder, tmp_path, monkeypatch):
        monkeypatch.setattr(tuning, "COMFYUI_GEN_FPS", 16)
        photo = _write_photo(tmp_path / "photo.jpg", (120, 120, 120))
        recorder.client.generate_clip(str(photo), str(tmp_path / "out.mp4"), 2.0, "pan-right")

        assert len(recorder.joined) == 1
        assert not list(tmp_path.glob("*.gen.mp4"))

    def test_the_a14b_model_always_chains(self, recorder, tmp_path, monkeypatch):
        monkeypatch.setattr(tuning, "COMFYUI_CHAIN_LAST_FRAME", False)
        monkeypatch.setattr(tuning, "COMFYUI_MODEL", "a14b")
        photo = _write_photo(tmp_path / "photo.jpg", (120, 120, 120))
        recorder.client.generate_clip(str(photo), str(tmp_path / "out.mp4"), LONG_ENOUGH, "pan-right")

        assert len(recorder.graphs) == 2 and len(recorder.joined) == 2
        assert all(g["55"]["class_type"] == "WanImageToVideo" for g in recorder.graphs)
