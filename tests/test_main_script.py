import subprocess
import sys


def test_main_py_can_run_as_direct_script(tmp_path):
    result = subprocess.run(
        [sys.executable, "src/main.py", "--mode", "popular", "--limit", "1", "--project-root", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert "web/data/dashboard.json" in result.stdout
