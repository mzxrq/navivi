import sys

from services import system_runtime


def test_a_dll_failure_is_told_apart_from_other_import_errors():
    assert system_runtime.looks_like_missing_runtime("OSError: [WinError 126] The specified module could not be found. Error loading c10.dll")
    assert not system_runtime.looks_like_missing_runtime("ModuleNotFoundError: No module named 'kokoro'")


def test_the_message_names_the_runtime_only_when_it_is_missing(monkeypatch):
    monkeypatch.setattr(system_runtime, "vc_runtime_installed", lambda: False)
    assert "Visual C++" in system_runtime.missing_runtime_message("The fast voice")
    monkeypatch.setattr(system_runtime, "vc_runtime_installed", lambda: True)
    assert system_runtime.missing_runtime_message("The fast voice") == ""


def test_an_import_failure_carries_the_reason(monkeypatch):
    monkeypatch.setattr(system_runtime, "vc_runtime_installed", lambda: False)
    text = system_runtime.import_failure(sys.executable, "raise ImportError('DLL load failed while importing c10')", "Kokoro")
    assert "Visual C++" in text and "DLL load failed" in text
    monkeypatch.setattr(system_runtime, "vc_runtime_installed", lambda: True)
    text = system_runtime.import_failure(sys.executable, "import no_such_module_here", "Kokoro")
    assert "could not be imported" in text and "no_such_module_here" in text
    assert system_runtime.import_failure(sys.executable, "pass", "Kokoro") == ""
