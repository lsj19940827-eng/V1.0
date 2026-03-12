# -*- coding: utf-8 -*-
"""
report_meta 配置单元测试（有压管道模块）

校验：
1) REFERENCES_BASE['pressure_pipe'] 同时包含 GB 50288 与 GB/T 20203
2) CALC_PURPOSE_TEMPLATE['pressure_pipe'] 使用双规范并列表述
"""

import ast
from pathlib import Path


REPORT_META_PATH = Path(__file__).resolve().parents[1] / "app_渠系计算前端" / "report_meta.py"


def _read_dict_literal(var_name: str):
    source = REPORT_META_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(REPORT_META_PATH))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == var_name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"未找到变量: {var_name}")


def test_pressure_pipe_references_include_dual_standards():
    references_base = _read_dict_literal("REFERENCES_BASE")
    pressure_refs = references_base["pressure_pipe"]
    assert "《灌溉与排水工程设计标准》(GB 50288-2018)" in pressure_refs
    assert "《管道输水灌溉工程技术规范》(GB/T 20203-2017)" in pressure_refs


def test_pressure_pipe_calc_purpose_mentions_dual_standards():
    calc_purpose_template = _read_dict_literal("CALC_PURPOSE_TEMPLATE")
    purpose = calc_purpose_template["pressure_pipe"]
    assert "GB 50288-2018" in purpose
    assert "GB/T 20203-2017" in purpose
