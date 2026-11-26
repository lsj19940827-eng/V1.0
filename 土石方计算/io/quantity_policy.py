"""Shared quantity-basis notes for saved section deliverables."""
from __future__ import annotations


def _recorded_overlap_policies(payload):
    """Both service snapshots and low-level results record their quantity basis."""
    accuracy = (payload.get("inputs") or {}).get("accuracy") or {}
    policies = [record.get("overlap_policy") for record in (
        payload, accuracy, payload.get("validation") or {}, payload.get("input_metadata") or {})
        if record.get("overlap_policy") is not None]
    allocation = {"independent_sections_no_overlap_deduction": "independent_sections",
                  "section_Z_interval_station_first_owner": "spatial_union"}.get(payload.get("allocation_policy"))
    if allocation is not None:
        policies.append(allocation)
    return policies


def uses_independent_sections(payload):
    """Require explicit current inputs with no conflicting recorded policy."""
    accuracy = (payload.get("inputs") or {}).get("accuracy") or {}
    return (accuracy.get("overlap_policy") == "independent_sections"
            and all(policy == "independent_sections" for policy in _recorded_overlap_policies(payload)))


def require_independent_section_export(payload):
    """Block old deductions from being published as a new formal deliverable.

    Workbench results must explicitly record the current policy. Legacy
    low-level section records without a policy remain readable/exportable,
    but an explicitly recorded different policy is never silently relabelled.
    """
    policies = _recorded_overlap_policies(payload)
    if (any(policy != "independent_sections" for policy in policies)
            or payload.get("kind") == "workbench" and not uses_independent_sections(payload)):
        raise ValueError("成果未采用各断面分别计量口径，请重新计算后另存；历史断面、数量和标识仍保留")


def overlap_policy_note(payload):
    """Describe the recorded policy without relabelling historical results."""
    policies = _recorded_overlap_policies(payload)
    if policies and all(policy == "independent_sections" for policy in policies):
        return "各断面分别计量，不扣除相邻区段或自交的重叠；单断面自身结构占位仍按现行规则扣除。"
    return ""


def delivery_method_note(payload):
    note = overlap_policy_note(payload)
    if note:
        return "断面法按原始地形生成地面线并沿路线分段积分；" + note
    return "断面法按原始地形生成地面线并沿路线分段积分；相邻区段接头按混凝土优先、垫层扣重处理，具体工程近似见表格和图纸说明。"
