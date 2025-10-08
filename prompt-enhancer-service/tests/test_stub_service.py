from __future__ import annotations

import subprocess
from pathlib import Path

from src.enhancer import Request
from src.mode_command import CommandService


def test_stub_service_passes_rendered_prompt(monkeypatch, tmp_path):
    template_path = tmp_path / "template.txt"
    template_path.write_text("wrapped: {{ prompt }}")

    temp_root = tmp_path / "files"
    monkeypatch.setattr("src.enhancer.TEMP_ROOT_DIR", temp_root)

    captured = {}

    def fake_run(cmd, check, capture_output, text):
        captured["cmd"] = cmd
        captured["in_content"] = Path(cmd[2]).read_text()
        out_path = Path(cmd[-1])
        out_path.write_text("###start###\nwrapped: hello\n###end###\n")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    service = CommandService("/bin/true", str(template_path), auto_cleanup_enabled=True)

    resp = service.enhance(Request(prompt="hello"))

    assert resp.prompt == "wrapped: hello\n"
    assert captured["in_content"] == "wrapped: hello"
    assert not temp_root.exists()


def test_command_service_persists_files_when_cleanup_disabled(monkeypatch, tmp_path):
    template_path = tmp_path / "template.txt"
    template_path.write_text("wrapped: {{ prompt }}")

    temp_root = tmp_path / "files"
    monkeypatch.setattr("src.enhancer.TEMP_ROOT_DIR", temp_root)

    captured = {}

    def fake_run(cmd, check, capture_output, text):
        captured["cmd"] = cmd
        captured["in_path"] = Path(cmd[2])
        captured["out_path"] = Path(cmd[-1])
        captured["in_content"] = captured["in_path"].read_text()
        captured["out_path"].write_text("###start###\nwrapped: hello\n###end###\n")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    service = CommandService("/bin/true", str(template_path), auto_cleanup_enabled=False)

    resp = service.enhance(Request(prompt="hello"))

    assert resp.prompt == "wrapped: hello\n"
    assert captured["in_content"] == "wrapped: hello"
    assert temp_root.exists()
    files = list(temp_root.iterdir())
    assert len(files) == 2
    in_file = captured["in_path"]
    out_file = captured["out_path"]
    assert in_file.name.endswith("_in.txt")
    assert out_file.name.endswith("_out.txt")
    assert in_file.name.split("_", 1)[0] == out_file.name.split("_", 1)[0]
    assert in_file.read_text() == "wrapped: hello"
    assert out_file.read_text() == "###start###\nwrapped: hello\n###end###\n"
