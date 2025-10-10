from __future__ import annotations

from pathlib import Path

import pytest

from src.template_utils import TemplateError, resolve_template_path


def test_resolve_template_path_prefers_locale(tmp_path):
    base_dir = Path(tmp_path)
    (base_dir / "default.txt").write_text("base")
    (base_dir / "default_cn.txt").write_text("cn")

    resolved = resolve_template_path(base_dir, "default", "CN")

    assert resolved == base_dir / "default_cn.txt"


def test_resolve_template_path_falls_back_to_default(tmp_path):
    base_dir = Path(tmp_path)
    (base_dir / "default.txt").write_text("base")

    resolved = resolve_template_path(base_dir, "default", "cn")

    assert resolved == base_dir / "default.txt"


def test_resolve_template_path_errors_when_missing(tmp_path):
    base_dir = Path(tmp_path)

    with pytest.raises(TemplateError):
        resolve_template_path(base_dir, "default", "cn")
