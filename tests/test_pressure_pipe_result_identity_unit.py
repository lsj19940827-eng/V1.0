# -*- coding: utf-8 -*-
"""有压管道结果身份键单元测试。"""

from 推求水面线.utils.pressure_pipe_result_helpers import make_pressure_pipe_identity


def test_identity_uses_flow_section_and_name():
    """同名跨流量段必须生成不同身份键。"""
    k1 = make_pressure_pipe_identity("1", "牛马道")
    k2 = make_pressure_pipe_identity("2", "牛马道")
    assert k1 != k2
    assert k1 == "1::牛马道"
    assert k2 == "2::牛马道"


def test_identity_has_fallback_values():
    """缺省字段应回退到稳定默认值。"""
    k = make_pressure_pipe_identity("", "")
    assert k == "-::未命名"
