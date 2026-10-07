from services.tts import qwen3_setup


def _setup(monkeypatch, tmp_path, backend, imports_work, cuda_torch):
    runs = []
    python = tmp_path / "python.exe"
    python.write_text("")
    monkeypatch.setattr(qwen3_setup.Qwen3TTSClient, "_SERVER_DIR", tmp_path)
    monkeypatch.setattr(qwen3_setup.Qwen3TTSClient, "_SERVER_VENV_PYTHON", python)
    monkeypatch.setattr(qwen3_setup.Qwen3TTSClient, "_READY_FILE", tmp_path / ".ready")
    monkeypatch.setattr(qwen3_setup.tuning, "QWEN3_DEVICE", "cuda")
    monkeypatch.setattr(qwen3_setup, "pick_backend", lambda: backend)
    monkeypatch.setattr(qwen3_setup, "find_uv", lambda: "uv")
    monkeypatch.setattr(qwen3_setup, "_imports_work", lambda p: imports_work)
    monkeypatch.setattr(qwen3_setup, "_has_cuda_torch", lambda p: cuda_torch)
    monkeypatch.setattr(qwen3_setup, "_run", lambda cmd, what: runs.append((what, cmd)))
    return runs


def test_a_cpu_setup_on_an_nvidia_pc_gets_the_gpu_torch(monkeypatch, tmp_path):
    runs = _setup(monkeypatch, tmp_path, "cu128", imports_work=True, cuda_torch=False)
    assert qwen3_setup.install_qwen3()["success"]
    what, cmd = runs[0]
    assert what == "installing torch (GPU)" and qwen3_setup.CUDA_TORCH_INDEX in cmd and "torchaudio" in cmd


def test_a_gpu_setup_is_left_alone(monkeypatch, tmp_path):
    runs = _setup(monkeypatch, tmp_path, "cu128", imports_work=True, cuda_torch=True)
    qwen3_setup.install_qwen3()
    assert [what for what, _ in runs] == ["downloading the model (about 2.5 GB)"]


def test_without_an_nvidia_gpu_torch_stays_on_the_cpu(monkeypatch, tmp_path):
    runs = _setup(monkeypatch, tmp_path, "cpu", imports_work=True, cuda_torch=False)
    qwen3_setup.install_qwen3()
    assert not any("GPU" in what for what, _ in runs)
