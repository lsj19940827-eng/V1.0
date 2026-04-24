# -*- coding: utf-8 -*-
"""
有压管道结果展示/持久化辅助函数（纯函数，无 UI 依赖）。
"""

import copy
from typing import Any, Dict, List, Optional

LEGACY_SPATIAL_RESULT_NOTE = "旧空间合并结果，请按新口径重新计算"


def make_pressure_pipe_identity(flow_section: Any, name: Any) -> str:
    """构造有压管道稳定身份键：流量段+名称。"""
    fs = str(flow_section).strip() if flow_section is not None else ""
    nm = str(name).strip() if name is not None else ""
    if not fs:
        fs = "-"
    if not nm:
        nm = "未命名"
    return f"{fs}::{nm}"


def empty_pressure_pipe_calc_records() -> Dict[str, Any]:
    """返回空的有压管道计算记录结构。"""
    return {
        "last_run_at": "",
        "summary": {"total": 0, "success": 0, "failed": 0},
        "records": [],
        "chain_summaries": [],
    }


def _to_float_or_none(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_bool_or_default(v: Any, default: bool) -> bool:
    """将值转换为布尔值，无法判断时回退到默认值。"""
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        text = v.strip().lower()
        if text in ("true", "1", "yes", "y", "是"):
            return True
        if text in ("false", "0", "no", "n", "否"):
            return False
        return default
    return bool(v)


def _to_row_index_or_default(v: Any, default: int = -1) -> int:
    """将行索引转换为整数，保留合法的 0。"""
    if v is None:
        return default
    if isinstance(v, str) and not v.strip():
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def is_legacy_spatial_mode(data_mode: Any) -> bool:
    """判断是否为旧空间合并口径的历史结果。"""
    text = str(data_mode or "").strip()
    if not text:
        return False
    return "空间模式" in text or "空间合并" in text


def append_legacy_spatial_result_note(note: Any, data_mode: Any) -> str:
    """为旧空间合并结果追加重算提示。"""
    base = str(note or "").strip()
    if not is_legacy_spatial_mode(data_mode):
        return base
    if LEGACY_SPATIAL_RESULT_NOTE in base:
        return base
    if not base:
        return LEGACY_SPATIAL_RESULT_NOTE
    return f"{base}；{LEGACY_SPATIAL_RESULT_NOTE}"


def build_pressure_pipe_transition_note(
    has_inlet_transition: bool = True,
    inlet_transition_reason: str = "",
    has_outlet_transition: bool = True,
    outlet_transition_reason: str = "",
) -> str:
    """汇总进口/出口两侧“无渐变段”说明。"""
    notes: List[str] = []

    inlet_reason = str(inlet_transition_reason or "").strip()
    outlet_reason = str(outlet_transition_reason or "").strip()

    if not has_inlet_transition:
        notes.append(f"进口侧{inlet_reason or '无渐变段'}")
    if not has_outlet_transition:
        notes.append(f"出口侧{outlet_reason or '无渐变段'}")

    return "；".join(notes)


def normalize_pressure_pipe_calc_records(raw: Any) -> Dict[str, Any]:
    """
    规范化记录结构，兼容缺失字段/旧项目数据。
    """
    out = empty_pressure_pipe_calc_records()
    if not isinstance(raw, dict):
        return out

    out["last_run_at"] = str(raw.get("last_run_at", "") or "")

    normalized_records: List[Dict[str, Any]] = []
    for rec in raw.get("records", []) or []:
        if not isinstance(rec, dict):
            continue

        flow_section = str(rec.get("flow_section", "") or "")
        name = str(rec.get("name", "") or "")
        identity = str(rec.get("identity", "") or make_pressure_pipe_identity(flow_section, name))

        status = str(rec.get("status", "failed") or "failed").lower()
        if status not in ("success", "failed"):
            status = "failed"

        row = {
            "identity": identity,
            "flow_section": flow_section,
            "name": name,
            "display_name": str(rec.get("display_name", "") or name or ""),
            "structure_type": str(rec.get("structure_type", "") or "").strip(),
            "storage_key": str(rec.get("storage_key", "") or identity),
            "group_mode": str(rec.get("group_mode", "") or ""),
            "status": status,
            "writeback_enabled": _to_bool_or_default(rec.get("writeback_enabled"), True),
            "data_mode": str(rec.get("data_mode", "") or ""),
            "Q": _to_float_or_none(rec.get("Q")),
            "D": _to_float_or_none(rec.get("D")),
            "material_key": str(rec.get("material_key", "") or ""),
            "resolved_material_key": str(rec.get("resolved_material_key", "") or ""),
            "total_length": _to_float_or_none(rec.get("total_length")),
            "pipe_velocity": _to_float_or_none(rec.get("pipe_velocity")),
            "friction_loss": _to_float_or_none(rec.get("friction_loss")),
            "total_bend_loss": _to_float_or_none(rec.get("total_bend_loss")),
            "local_loss": _to_float_or_none(rec.get("local_loss")),
            "inlet_transition_loss": _to_float_or_none(rec.get("inlet_transition_loss")),
            "outlet_transition_loss": _to_float_or_none(rec.get("outlet_transition_loss")),
            "total_head_loss": _to_float_or_none(rec.get("total_head_loss")),
            "target_row_index": _to_row_index_or_default(rec.get("target_row_index", -1)),
            "upstream_row_index": _to_row_index_or_default(rec.get("upstream_row_index", -1)),
            "sensitivity_material": str(rec.get("sensitivity_material", "") or ""),
            "sensitivity_main_f": _to_float_or_none(rec.get("sensitivity_main_f")),
            "sensitivity_low_f": _to_float_or_none(rec.get("sensitivity_low_f")),
            "sensitivity_low_friction_loss": _to_float_or_none(rec.get("sensitivity_low_friction_loss")),
            "sensitivity_low_total_head_loss": _to_float_or_none(rec.get("sensitivity_low_total_head_loss")),
            "sensitivity_delta_total_head_loss": _to_float_or_none(rec.get("sensitivity_delta_total_head_loss")),
            "has_inlet_transition": _to_bool_or_default(rec.get("has_inlet_transition"), True),
            "has_outlet_transition": _to_bool_or_default(rec.get("has_outlet_transition"), True),
            "inlet_transition_reason": str(rec.get("inlet_transition_reason", "") or ""),
            "outlet_transition_reason": str(rec.get("outlet_transition_reason", "") or ""),
            "calc_steps": str(rec.get("calc_steps", "") or ""),
            "error": str(rec.get("error", "") or ""),
            "note": str(rec.get("note", "") or ""),
            "friction_details": copy.deepcopy(rec.get("friction_details", {}) or {})
            if isinstance(rec.get("friction_details"), dict) else {},
            "bend_details": copy.deepcopy(rec.get("bend_details", {}) or {})
            if isinstance(rec.get("bend_details"), dict) else {},
            "local_details": copy.deepcopy(rec.get("local_details", {}) or {})
            if isinstance(rec.get("local_details"), dict) else {},
        }
        if not row["note"]:
            row["note"] = build_pressure_pipe_transition_note(
                has_inlet_transition=row["has_inlet_transition"],
                inlet_transition_reason=row["inlet_transition_reason"],
                has_outlet_transition=row["has_outlet_transition"],
                outlet_transition_reason=row["outlet_transition_reason"],
            )
        row["note"] = append_legacy_spatial_result_note(row["note"], row["data_mode"])
        normalized_records.append(row)

    normalized_chain_summaries: List[Dict[str, Any]] = []
    for chain in raw.get("chain_summaries", []) or []:
        if not isinstance(chain, dict):
            continue

        flow_section = str(chain.get("flow_section", "") or "")
        display_name = str(chain.get("display_name", "") or "").strip() or "未命名连续承压链"
        chain_id = str(chain.get("chain_id", "") or "").strip()
        if not chain_id:
            chain_id = make_pressure_pipe_identity(flow_section or "-", display_name)

        member_results: List[Dict[str, Any]] = []
        for member in chain.get("member_results", []) or []:
            if not isinstance(member, dict):
                continue
            member_status = str(member.get("status", "failed") or "failed").lower()
            if member_status not in ("success", "failed"):
                member_status = "failed"
            member_results.append({
                "identity": str(member.get("identity", "") or "").strip(),
                "display_name": str(
                    member.get("display_name", member.get("name", "")) or ""
                ).strip() or "未命名成员",
                "structure_type": str(member.get("structure_type", "") or "").strip() or "-",
                "status": member_status,
                "writeback_enabled": _to_bool_or_default(member.get("writeback_enabled"), True),
                "total_head_loss": _to_float_or_none(member.get("total_head_loss")),
                "error": str(member.get("error", "") or "").strip(),
                "note": str(member.get("note", "") or "").strip(),
            })

        success_count = sum(1 for item in member_results if item.get("status") == "success")
        failed_count = len(member_results) - success_count
        chain_complete_default = failed_count <= 0
        chain_complete = _to_bool_or_default(chain.get("chain_complete"), chain_complete_default)
        chain_status = str(chain.get("chain_status", "") or "").strip().lower()
        if chain_status not in ("complete", "incomplete"):
            chain_status = "complete" if chain_complete else "incomplete"
        normalized_chain_summaries.append({
            "chain_id": chain_id,
            "flow_section": flow_section,
            "display_name": display_name,
            "chain_complete": chain_complete,
            "chain_status": chain_status,
            "total_head_loss": _to_float_or_none(chain.get("total_head_loss")) if chain_complete else None,
            "member_count": int(chain.get("member_count", len(member_results)) or len(member_results)),
            "success_count": int(chain.get("success_count", success_count) or success_count),
            "failed_count": int(chain.get("failed_count", failed_count) or failed_count),
            "member_results": member_results,
        })

    total = len(normalized_records)
    success = sum(1 for r in normalized_records if r.get("status") == "success")
    failed = total - success
    out["records"] = normalized_records
    out["chain_summaries"] = normalized_chain_summaries
    out["summary"] = {"total": total, "success": success, "failed": failed}
    return out


def _fmt_num(v: Any, precision: int = 4) -> str:
    fv = _to_float_or_none(v)
    if fv is None:
        return "-"
    return f"{fv:.{precision}f}"


def format_pressure_pipe_record_detail(record: Dict[str, Any], precision: int = 4) -> str:
    """将单条记录格式化为结构化纯文本。"""
    status = "成功" if record.get("status") == "success" else "失败"
    flow_section = record.get("flow_section", "") or "-"
    name = record.get("name", "") or "未命名"
    data_mode = (record.get("data_mode", "") or "").strip()
    mode_suffix = f"  数据模式={data_mode}" if data_mode else ""
    lines = [f"[{status}] 流量段={flow_section}  名称={name}{mode_suffix}"]

    if record.get("status") == "success":
        if not record.get("writeback_enabled", True):
            note = (record.get("note", "") or "").strip() or "本行仅作为起点，不计算本行水头损失"
            lines.append(f"说明: {note}")
            steps = (record.get("calc_steps", "") or "").strip()
            if steps:
                lines.append("计算过程:")
                lines.append(steps)
            return "\n".join(lines)

        material_text = (
            str(record.get("material_key", "") or "").strip()
            or str(record.get("resolved_material_key", "") or "").strip()
            or "-"
        )
        lines.append(
            "输入参数: "
            f"Q={_fmt_num(record.get('Q'), precision)} m3/s, "
            f"D={_fmt_num(record.get('D'), precision)} m, "
            f"管材={material_text}, "
            f"L={_fmt_num(record.get('total_length'), precision)} m, "
            f"V={_fmt_num(record.get('pipe_velocity'), precision)} m/s"
        )
        loss_parts = [
            f"沿程={_fmt_num(record.get('friction_loss'), precision)} m",
            f"弯头={_fmt_num(record.get('total_bend_loss'), precision)} m",
        ]
        common_local = _to_float_or_none(record.get("local_loss"))
        if common_local is not None and abs(common_local) > 1e-12:
            loss_parts.append(f"通用构件={_fmt_num(common_local, precision)} m")
        loss_parts.extend([
            f"进口渐变={_fmt_num(record.get('inlet_transition_loss'), precision)} m",
            f"出口渐变={_fmt_num(record.get('outlet_transition_loss'), precision)} m",
        ])
        lines.append("分项损失: " + ", ".join(loss_parts))
        lines.append(f"总损失: ΔH={_fmt_num(record.get('total_head_loss'), precision)} m")
        sens_low_total = _to_float_or_none(record.get("sensitivity_low_total_head_loss"))
        if sens_low_total is not None:
            sens_mat = record.get("sensitivity_material", "") or "球墨铸铁管"
            main_f = record.get("sensitivity_main_f")
            low_f = record.get("sensitivity_low_f")
            lines.append(
                f"规范上下限对比: 管材={sens_mat}, f主值={main_f}, f下限={low_f}（仅对比，不影响主结果）"
            )
            lines.append(
                "  对比结果: "
                f"沿程(下限f)={_fmt_num(record.get('sensitivity_low_friction_loss'), precision)} m, "
                f"总损失(下限f)={_fmt_num(sens_low_total, precision)} m, "
                f"ΔH(下限-主值)={_fmt_num(record.get('sensitivity_delta_total_head_loss'), precision)} m"
            )
        note = (record.get("note", "") or "").strip()
        if note:
            lines.append(f"备注: {note}")
        steps = (record.get("calc_steps", "") or "").strip()
        if steps:
            lines.append("计算过程:")
            lines.append(steps)
    else:
        err = (record.get("error", "") or "").strip() or "未知错误"
        lines.append(f"失败原因: {err}")
        note = (record.get("note", "") or "").strip()
        if note:
            lines.append(f"备注: {note}")
    return "\n".join(lines)


def format_pressure_pipe_chain_summary(chain_summary: Dict[str, Any], precision: int = 4) -> str:
    """将单条连续承压链汇总格式化为纯文本。"""
    flow_section = chain_summary.get("flow_section", "") or "-"
    display_name = chain_summary.get("display_name", "") or "未命名连续承压链"
    total_head_loss = _fmt_num(chain_summary.get("total_head_loss"), precision)
    member_count = int(chain_summary.get("member_count", 0) or 0)
    success_count = int(chain_summary.get("success_count", 0) or 0)
    failed_count = int(chain_summary.get("failed_count", 0) or 0)
    chain_complete = _to_bool_or_default(chain_summary.get("chain_complete"), failed_count <= 0)
    chain_status = "已完成" if chain_complete else "未完成"

    lines = [
        f"流量段={flow_section}  链路={display_name}",
        f"整线状态: {chain_status}",
        f"成员统计: 共{member_count}个，成功{success_count}个，失败{failed_count}个",
    ]
    if chain_complete:
        lines.insert(2, f"链总损失: ΔH={total_head_loss} m")

    for idx, member in enumerate(chain_summary.get("member_results", []) or [], 1):
        structure_type = member.get("structure_type", "") or "-"
        display_text = member.get("display_name", "") or "未命名成员"
        if member.get("status") == "success" and not member.get("writeback_enabled", True):
            lines.append(f"成员{idx}: {structure_type} | {display_text} | 锚点")
            continue
        if member.get("status") == "success":
            lines.append(
                f"成员{idx}: {structure_type} | {display_text} | "
                f"ΔH={_fmt_num(member.get('total_head_loss'), precision)} m"
            )
            continue
        error_text = member.get("error", "") or member.get("note", "") or "未知错误"
        lines.append(f"成员{idx}: {structure_type} | {display_text} | 失败: {error_text}")

    return "\n".join(lines)


def format_pressure_pipe_calc_batch_text(batch: Dict[str, Any], precision: int = 4) -> str:
    """将批次记录格式化为可追加到 detail_text 的纯文本章节。"""
    normalized = normalize_pressure_pipe_calc_records(batch)
    records = normalized.get("records", [])
    chain_summaries = normalized.get("chain_summaries", [])
    if not records and not chain_summaries:
        return ""

    summary = normalized.get("summary", {})
    ts = normalized.get("last_run_at", "") or "-"
    has_sensitivity = any(rec.get("sensitivity_low_total_head_loss") is not None for rec in records)
    has_tunnel_hydraulic_display = any("隧洞" in str(rec.get("structure_type", "") or "") for rec in records)
    if not has_tunnel_hydraulic_display:
        for chain_summary in chain_summaries:
            for member in chain_summary.get("member_results", []) or []:
                if "隧洞" in str(member.get("structure_type", "") or ""):
                    has_tunnel_hydraulic_display = True
                    break
            if has_tunnel_hydraulic_display:
                break
    sensitivity_line = (
        "球墨铸铁管 f 上下限对比: 已自动生成"
        "（规范为区间取值：主值223200，下限189900；仅输出对比，不影响主结果回写）"
    ) if has_sensitivity else ""
    tunnel_mode_line = (
        "含隧洞水力核算模式：隧洞底线按计算结果反推显示，仅供水力核算，不作施工高程。"
    ) if has_tunnel_hydraulic_display else ""
    lines = [
        "=" * 80,
        f"【有压管道计算详情】  时间: {ts}",
    ]
    if sensitivity_line:
        lines.append(sensitivity_line)
    if tunnel_mode_line:
        lines.append(tunnel_mode_line)
    lines += [
        f"批次汇总: 共{summary.get('total', 0)}条，成功{summary.get('success', 0)}条，失败{summary.get('failed', 0)}条",
        "-" * 80,
    ]

    if chain_summaries:
        lines.append("【连续承压链汇总】")
        for i, chain_summary in enumerate(chain_summaries, 1):
            lines.append(f"{i}. {format_pressure_pipe_chain_summary(chain_summary, precision=precision)}")
            lines.append("")
        lines.append("-" * 80)

    for i, rec in enumerate(records, 1):
        lines.append(f"{i}. {format_pressure_pipe_record_detail(rec, precision=precision)}")
        lines.append("")
    return "\n".join(lines).rstrip()


def append_pressure_pipe_calc_batch_text(existing_text: str, batch: Dict[str, Any], precision: int = 4) -> str:
    """将批次章节追加到既有文本末尾。"""
    chapter = format_pressure_pipe_calc_batch_text(batch, precision=precision)
    if not chapter:
        return existing_text or ""
    base = existing_text or ""
    if base and not base.endswith("\n"):
        base += "\n"
    return (base + "\n" + chapter).lstrip("\n")
