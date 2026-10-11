# -*- coding: utf-8 -*-
"""架构检查必须识别真正覆盖，同时保留 property 和纯数据适配层。"""
from pathlib import Path
import subprocess
import sys

import pytest

from tools.check_architecture import check_source, check_paths


def test_duplicate_method_reports_class_and_both_definitions():
    issues = check_source("class Engine:\n def calc(self): return 1\n def calc(self): return 2\n",
                          "calc_渠系计算算法内核/example.py")
    assert len(issues) == 1
    assert issues[0].rule == "duplicate-method"
    assert issues[0].line == 3
    assert "Engine.calc" in issues[0].message
    assert "2, 3" in issues[0].message


def test_property_accessors_and_overloads_are_legitimate():
    source = """
class State:
    @property
    def value(self): return self._value
    @value.setter
    def value(self, value): self._value = value
    @value.deleter
    def value(self): del self._value
    @overload
    def read(self, key: int): ...
    @overload
    def read(self, key: str): ...
    def read(self, key): return key
"""
    assert check_source(source, "推求水面线/models/example.py") == []


def test_unrelated_setter_does_not_hide_duplicate_function():
    issues = check_source("class State:\n def value(self): pass\n @other.setter\n def value(self, value): pass\n",
                          "推求水面线/models/example.py")
    assert [issue.rule for issue in issues] == ["duplicate-method"]


def test_nested_classes_are_checked_independently():
    source = """
class A:
    def calc(self): return 1
    class B:
        def calc(self): return 2
class C:
    def calc(self): return 3
"""
    assert check_source(source, "app_渠系计算前端/example.py") == []


def test_nested_optional_and_dynamic_ui_imports_are_rejected_in_domain():
    source = """
def calc():
    try:
        from PySide6.QtCore import QObject
    except ImportError:
        pass
    return importlib.import_module('app_渠系计算前端.water_profile.panel')
"""
    issues = check_source(source, "推求水面线/core/example.py")
    assert len(issues) == 2
    assert all(issue.rule == "domain-ui-import" for issue in issues)


def test_pure_frontend_adapter_can_import_only_approved_data_modules():
    valid = "from .schema import INPUT_HEADERS\nfrom . import engines\nfrom app_渠系计算前端.increase_input_helper import get_auto_increase_percent\n"
    assert check_source(valid, "app_渠系计算前端/batch/calculation_service.py") == []
    for source in ("from .panel import BatchPanel", "from .. import styles", "from PySide6 import QtCore"):
        issues = check_source(source, "app_渠系计算前端/batch/calculation_service.py")
        assert len(issues) == 1
        assert issues[0].rule == "domain-ui-import"


def test_domain_cannot_reach_back_even_to_frontend_data_adapter():
    source = "from app_渠系计算前端.report_meta_model import ReportMeta"
    assert check_source(source, "推求水面线/models/example.py")[0].rule == "domain-ui-import"



def test_tool_reads_sources_without_executing_top_level_code(tmp_path):
    folder = tmp_path / "calc_渠系计算算法内核"
    folder.mkdir()
    (folder / "example.py").write_text("raise RuntimeError('不可执行')\nclass C:\n def value(self): return 1\n", encoding="utf-8")
    files, issues = check_paths(tmp_path)
    assert len(files) == 1
    assert not issues


def test_syntax_errors_are_findings_not_silently_skipped():
    issues = check_source("class Broken:\n", "app_渠系计算前端/example.py")
    assert len(issues) == 1
    assert issues[0].rule == "syntax"


def test_production_architecture_contract():
    files, issues = check_paths(Path(__file__).resolve().parents[1])
    assert files
    assert not issues, "\n".join(f"{issue.path}:{issue.line}: {issue.message}" for issue in issues)
