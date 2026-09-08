"""Unit tests for services/config/job_config.py.

JobConfigManager is a process-wide singleton; the autouse
`_isolated_job_config_singleton` fixture in conftest.py resets it before and
after every test so tests don't leak state into each other.
"""

import json

import pytest

from services.config.job_config import JobConfigManager


def _write_config(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestLoad:
    def test_loads_existing_file_on_init(self, tmp_path):
        config_path = _write_config(
            tmp_path / "job_config.json", {"project_name": "Test"}
        )
        manager = JobConfigManager(config_path)
        assert manager.get("project_name") == "Test"

    def test_missing_file_starts_with_empty_data(self, tmp_path):
        manager = JobConfigManager(tmp_path / "does_not_exist.json")
        assert manager.to_dict() == {}

    def test_load_raises_if_file_missing(self, tmp_path):
        manager = JobConfigManager(tmp_path / "does_not_exist.json")
        with pytest.raises(FileNotFoundError):
            manager.load()

    def test_load_raises_on_invalid_json(self, tmp_path):
        bad_path = tmp_path / "job_config.json"
        bad_path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            JobConfigManager(bad_path)


class TestGetSet:
    def test_get_returns_default_when_missing(self, tmp_path):
        manager = JobConfigManager(tmp_path / "job_config.json")
        assert manager.get("missing_key", "fallback") == "fallback"

    def test_set_then_get_roundtrip(self, tmp_path):
        manager = JobConfigManager(tmp_path / "job_config.json")
        manager.set("project_name", "MyTrip")
        assert manager.get("project_name") == "MyTrip"


class TestWaypoints:
    def test_get_waypoints_empty_by_default(self, tmp_path):
        manager = JobConfigManager(tmp_path / "job_config.json")
        assert manager.get_waypoints() == []

    def test_add_waypoint_appends(self, tmp_path):
        manager = JobConfigManager(tmp_path / "job_config.json")
        manager.add_waypoint({"label": "Osaka"})
        manager.add_waypoint({"label": "Kyoto"})
        waypoints = manager.get_waypoints()
        assert len(waypoints) == 2
        assert waypoints[0]["label"] == "Osaka"
        assert waypoints[1]["label"] == "Kyoto"


class TestSettings:
    def test_get_settings_empty_by_default(self, tmp_path):
        manager = JobConfigManager(tmp_path / "job_config.json")
        assert manager.get_settings() == {}

    def test_update_settings_merges_not_replaces(self, tmp_path):
        manager = JobConfigManager(tmp_path / "job_config.json")
        manager.update_settings({"fps": 30})
        manager.update_settings({"duration": 60})
        settings = manager.get_settings()
        assert settings == {"fps": 30, "duration": 60}

    def test_update_settings_overwrites_existing_key(self, tmp_path):
        manager = JobConfigManager(tmp_path / "job_config.json")
        manager.update_settings({"fps": 30})
        manager.update_settings({"fps": 60})
        assert manager.get_settings()["fps"] == 60


class TestSave:
    def test_save_writes_to_original_config_path_by_default(self, tmp_path):
        config_path = tmp_path / "job_config.json"
        manager = JobConfigManager(config_path)
        manager.set("project_name", "Saved")
        manager.save()
        assert json.loads(config_path.read_text(encoding="utf-8")) == {
            "project_name": "Saved"
        }

    def test_save_prefers_directory_path_field(self, tmp_path):
        alt_dir = tmp_path / "elsewhere"
        manager = JobConfigManager(tmp_path / "job_config.json")
        manager.set("directory_path", str(alt_dir))
        manager.save()
        saved_file = alt_dir / "job_config.json"
        assert saved_file.exists()
        assert manager.config_path == saved_file.resolve()

    def test_save_to_explicit_target_path(self, tmp_path):
        manager = JobConfigManager(tmp_path / "job_config.json")
        manager.set("project_name", "Explicit")
        target = tmp_path / "custom" / "out.json"
        manager.save(target)
        assert json.loads(target.read_text(encoding="utf-8"))["project_name"] == "Explicit"

    def test_save_preserves_non_ascii_text(self, tmp_path):
        config_path = tmp_path / "job_config.json"
        manager = JobConfigManager(config_path)
        manager.set("project_name", "大阪市")
        manager.save()
        assert "大阪市" in config_path.read_text(encoding="utf-8")


class TestSingletonBehavior:
    def test_repeated_construction_without_path_keeps_existing_data(self, tmp_path):
        config_path = _write_config(
            tmp_path / "job_config.json", {"project_name": "First"}
        )
        JobConfigManager(config_path)
        second_ref = JobConfigManager()
        assert second_ref.get("project_name") == "First"

    def test_new_path_argument_reloads_data(self, tmp_path):
        first_path = _write_config(tmp_path / "a.json", {"project_name": "A"})
        second_path = _write_config(tmp_path / "b.json", {"project_name": "B"})
        JobConfigManager(first_path)
        manager = JobConfigManager(second_path)
        assert manager.get("project_name") == "B"
