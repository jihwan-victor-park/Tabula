"""CP1.13: no credentials or runtime identity files are tracked."""

import subprocess
import sys


def test_tracked_files_contain_no_secrets():
    result = subprocess.run([sys.executable, "scripts/secret_scan.py", "--all"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_scanner_catches_a_planted_key(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("secret_scan", "scripts/secret_scan.py")
    scan = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scan)
    planted = tmp_path / "config.json"
    planted.write_text('{"token": "' + "a" * 43 + '"}\n')
    monkeypatch.setattr(scan, "_files", lambda all_tracked: [str(planted), ".openclaw/identity/device.json"])
    problems = scan.scan(all_tracked=True)
    assert any("json_token_value" in p for p in problems)
    assert any("must not be committed" in p for p in problems)
