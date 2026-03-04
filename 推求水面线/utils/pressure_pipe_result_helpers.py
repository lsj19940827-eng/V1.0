# -*- coding: utf-8 -*-
"""
有压管道结果展示/持久化辅助函数（纯函数，无 UI 依赖）。
"""

from typing import Any, Dict, List, Optional


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
        "sensitivity_enabled": False,
        "summary": {"total": 0, "success": 0, "failed": 0},
        "records": [],
    }


def _to_float_or_none(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def normalize_pressure_pipe_calc_records(raw: Any) -> Dict[str, Any]:
    """
    规范化记录结构，兼容缺失字段/旧项目数据。
    """
    out = empty_pressure_pipe_calc_records()
    if not isinstance(raw, dict):
        return out

    out["last_run_at"] = str(raw.get("last_run_at", "") or "")
    out["sensitivity_enabled"] = bool(raw.get("sensitivity_enabled", False))

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
            "status": status,
            "Q": _to_float_or_none(rec.get("Q")),
            "D": _to_float_or_none(rec.get("D")),
            "material_key": str(rec.get("material_key", "") or ""),
            "total_length": _to_float_or_none(rec.get("total_length")),
            "pipe_velocity": _to_float_or_none(rec.get("pipe_velocity")),
            "friction_loss": _to_float_or_none(rec.get("friction_loss")),
            "total_bend_loss": _to_float_or_none(rec.get("total_bend_loss")),
            "inlet_transition_loss": _to_float_or_none(rec.get("inlet_transition_loss")),
            "outlet_transition_loss": _to_float_or_none(rec.get("outlet_transition_loss")),
            "total_head_loss": _to_float_or_none(rec.get("total_head_loss")),
            "sensitivity_material": str(rec.get("sensitivity_material", "") or ""),
            "sensitivity_main_f": _to_float_or_none(rec.get("sensitivity_main_f")),
            "sensitivity_low_f": _to_float_or_none(rec.get("sensitivity_low_f")),
            "sensitivity_low_friction_loss": _to_float_or_none(rec.get("sensitivity_low_friction_loss")),
            "sensitivity_low_total_head_loss": _to_float_or_none(rec.get("sensitivity_low_total_head_loss")),
            "sensitivity_delta_total_head_loss": _to_float_or_none(rec.get("sensitivity_delta_total_head_loss")),
            "calc_steps": str(rec.get("calc_steps", "") or ""),
            "error": str(rec.get("error", "") or ""),
            "note": str(rec.get("note", "") or ""),
        }
        normalized_records.append(row)

    total = len(normalized_records)
    success = sum(1 for r in normalized_records if r.get("status") == "success")
    failed = total - success
    out["records"] = normalized_records
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
    lines = [f"[{status}] 流量段={flow_section}  名称={name}"]

    if record.get("status") == "success":
        lines.append(
            "输入参数: "
            f"Q={_fmt_num(record.get('Q'), precision)} m3/s, "
            f"D={_fmt_num(record.get('D'), precision)} m, "
            f"管材={record.get('material_key', '') or '-'}, "
            f"L={_fmt_num(record.get('total_length'), precision)} m, "
            f"V={_fmt_num(record.get('pipe_velocity'), precision)} m/s"
        )
        lines.append(
            "分项损失: "
            f"沿程={_fmt_num(record.get('friction_loss'), precision)} m, "
            f"弯头={_fmt_num(record.get('total_bend_loss'), precision)} m, "
            f"进口渐变={_fmt_num(record.get('inlet_transition_loss'), precision)} m, "
            f"出口渐变={_fmt_num(record.get('outlet_transition_loss'), precision)} m"
        )
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


def format_pressure_pipe_calc_batch_text(batch: Dict[str, Any], precision: int = 4) -> str:
    """将批次记录格式化为可追加到 detail_text 的纯文本章节。"""
    normalized = normalize_pressure_pipe_calc_records(batch)
    records = normalized.get("records", [])
    if not records:
        return ""

    summary = normalized.get("summary", {})
    ts = normalized.get("last_run_at", "") or "-"
    lines = [
        "=" * 80,
        f"【有压管道计算详情】  时间: {ts}",
        (
            "球墨铸铁管 f 上下限对比: "
            f"{'开启' if normalized.get('sensitivity_enabled') else '关闭'}"
            "（规范为区间取值：主值223200，下限189900；仅输出对比，不影响主结果回写）"
        ),
        f"批次汇总: 共{summary.get('total', 0)}条，成功{summary.get('success', 0)}条，失败{summary.get('failed', 0)}条",
        "-" * 80,
    ]

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
