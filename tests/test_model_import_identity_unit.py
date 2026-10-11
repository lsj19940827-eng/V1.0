# -*- coding: utf-8 -*-
"""旧脚本与正式包交叉加载时，节点和枚举必须保持同一身份。"""

from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("legacy_first", [False, True])
def test_model_identity_survives_codec_and_legacy_extractor_import(legacy_first):
    """复现先建节点、再加载编解码器、最后提取进出口的真实交叉顺序。"""
    script = f'''
import importlib, sys
from pathlib import Path
sys.path.insert(0, str(Path("推求水面线").resolve()))
first = "models" if {legacy_first!r} else "推求水面线.models"
enums = importlib.import_module(first + ".enums")
models = importlib.import_module(first + ".data_models")
inlet = models.ChannelNode(name="同一管道", structure_type=enums.StructureType.PRESSURE_PIPE,
                          in_out=enums.InOutType.INLET, flow=1.5, section_params={{"D": 1.0}})
outlet = models.ChannelNode(name="同一管道", structure_type=enums.StructureType.PRESSURE_PIPE,
                           in_out=enums.InOutType.OUTLET, flow=1.5, section_params={{"D": 1.0}})
importlib.import_module("推求水面线.models.profile_node_codec")
namespace = importlib.import_module("推求水面线")
assert namespace.models is importlib.import_module("models")
for name in ("enums", "data_models", "pressure_pipe_override", "profile_state"):
    assert importlib.import_module("models." + name) is importlib.import_module("推求水面线.models." + name)
extractor = importlib.import_module("core.pressure_pipe_data").PressurePipeDataExtractor
groups = extractor.extract_pressure_pipe_groups([inlet, outlet])
assert len(groups) == 1
assert groups[0].inlet_node is inlet
assert groups[0].outlet_node is outlet
assert groups[0].is_valid()
assert groups[0].diameter_D == 1.0
assert groups[0].flow == 1.5
'''
    result = subprocess.run([sys.executable, "-B", "-c", script], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
