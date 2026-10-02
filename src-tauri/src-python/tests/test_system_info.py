from services.cli.system_commands import system_info


def test_reports_memory_and_cores():
    info = system_info()
    assert info["success"] is True
    assert info["ram_total_gb"] > 0
    assert 0 < info["ram_available_gb"] <= info["ram_total_gb"]
    assert info["cpu_threads"] >= 1
