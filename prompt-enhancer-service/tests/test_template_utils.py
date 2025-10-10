from __future__ import annotations

from pathlib import Path

import pytest

from src.template_utils import TemplateError, resolve_template_path


@pytest.mark.parametrize("locale", ["CN", "Cn", "cN", "cn"])
def test_resolve_template_path_prefers_locale_case_insensitive(tmp_path, locale):
    base_dir = Path(tmp_path)
    (base_dir / "default.txt").write_text("base")
    (base_dir / "default_cn.txt").write_text("cn")

    resolved = resolve_template_path(base_dir, "default", locale)

    assert resolved == base_dir / "default_cn.txt"


def test_resolve_template_path_falls_back_to_default_when_locale_missing(tmp_path):
    base_dir = Path(tmp_path)
    (base_dir / "default.txt").write_text("base")

    resolved = resolve_template_path(base_dir, "default", "cn")

    assert resolved == base_dir / "default.txt"


@pytest.mark.parametrize("locale", [None, ""])
def test_resolve_template_path_uses_default_for_blank_locale(tmp_path, locale):
    base_dir = Path(tmp_path)
    (base_dir / "default.txt").write_text("base")

    resolved = resolve_template_path(base_dir, "default", locale)

    assert resolved == base_dir / "default.txt"


def test_resolve_template_path_errors_when_missing(tmp_path):
    base_dir = Path(tmp_path)

    with pytest.raises(TemplateError, match="template not found"):
        resolve_template_path(base_dir, "default", "cn")


def test_resolve_template_path_rejects_empty_template_name(tmp_path):
    base_dir = Path(tmp_path)

    with pytest.raises(TemplateError, match="must not be empty"):
        resolve_template_path(base_dir, "", None)
