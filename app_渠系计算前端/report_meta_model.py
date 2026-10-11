# -*- coding: utf-8 -*-
"""报告信息纯数据模型；工程数据与个人默认偏好分别恢复。"""

from dataclasses import dataclass, field
from typing import List

@dataclass
class ReportMeta:
    project_name: str = ""
    design_stage: str = "施工图"
    product_level: str = "三级"
    record_number: str = ""
    specialty: str = "水工"
    calculator: str = ""
    checker: str = ""
    reviewer: str = ""
    approver: str = ""
    volume_current: str = ""
    volume_total: str = ""
    basic_info: str = ""
    mandatory_clause: str = "无"
    extra_references: List[str] = field(default_factory=list)

