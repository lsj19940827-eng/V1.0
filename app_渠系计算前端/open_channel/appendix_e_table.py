# -*- coding: utf-8 -*-
"""Appendix E table payload and HTML builders."""

from __future__ import annotations

import html
import json
from pathlib import Path


APPENDIX_E_SUMMARY_NOTE = (
    "说明: α=1.00 为水力最佳断面(深窄), α 越大断面越宽浅, 面积增加但流速降低。"
)
APPENDIX_E_RUNTIME_ATTR = "data-appendix-e-tabulator-ready"
APPENDIX_E_RUNTIME_OK = "ready"
APPENDIX_E_RUNTIME_LOADING = "loading"
APPENDIX_E_RUNTIME_ERROR = "error"
APPENDIX_E_PROBE_SCRIPT = """
(function () {
  const bodyState = document.body ? document.body.getAttribute("data-appendix-e-tabulator-ready") : "";
  const host = document.getElementById("appendix-e-table");
  const table = host ? host.querySelector(".tabulator") : null;
  const errorText = window.__appendixETabulatorError || "";
  return JSON.stringify({
    ready: bodyState === "ready" && !!table,
    state: bodyState || "",
    hasTable: !!table,
    errorText: errorText
  });
})();
""".strip()


def _e(value) -> str:
    return html.escape(str(value))


def appendix_e_tabulator_dir(resources_dir: str | Path) -> Path:
    return Path(resources_dir) / "vendor" / "tabulator"


def appendix_e_probe_script() -> str:
    return APPENDIX_E_PROBE_SCRIPT


def make_appendix_e_payload(schemes, sel_b, sel_h, v_min, v_max):
    columns = [
        {
            "title": "α值",
            "field": "alpha",
            "kind": "number",
            "precision": 2,
            "hozAlign": "center",
            "headerHozAlign": "center",
            "width": 74,
            "minWidth": 70,
        },
        {
            "title": "方案类型",
            "field": "schemeType",
            "kind": "text",
            "hozAlign": "left",
            "headerHozAlign": "center",
            "width": 182,
            "minWidth": 164,
            "widthGrow": 2,
        },
        {
            "title": "底宽 B (m)",
            "field": "b",
            "kind": "number",
            "precision": 3,
            "hozAlign": "right",
            "headerHozAlign": "center",
            "width": 98,
            "minWidth": 94,
        },
        {
            "title": "水深 h (m)",
            "field": "h",
            "kind": "number",
            "precision": 3,
            "hozAlign": "right",
            "headerHozAlign": "center",
            "width": 98,
            "minWidth": 94,
        },
        {
            "title": "宽深比 β",
            "field": "beta",
            "kind": "number",
            "precision": 3,
            "hozAlign": "right",
            "headerHozAlign": "center",
            "width": 92,
            "minWidth": 88,
        },
        {
            "title": "流速 V (m/s)",
            "field": "velocity",
            "kind": "number",
            "precision": 3,
            "hozAlign": "right",
            "headerHozAlign": "center",
            "width": 104,
            "minWidth": 100,
        },
        {
            "title": "面积增加",
            "field": "areaIncreaseLabel",
            "kind": "text",
            "hozAlign": "center",
            "headerHozAlign": "center",
            "width": 86,
            "minWidth": 82,
        },
        {
            "title": "状态",
            "field": "statusLabel",
            "kind": "status",
            "hozAlign": "center",
            "headerHozAlign": "center",
            "width": 94,
            "minWidth": 90,
        },
    ]

    rows = []
    selected_row = None
    for idx, scheme in enumerate(schemes, start=1):
        b_val = float(scheme["b"])
        h_val = float(scheme["h"])
        velocity = float(scheme["V"])
        is_selected = abs(b_val - sel_b) < 0.01 and abs(h_val - sel_h) < 0.01
        velocity_ok = v_min < velocity < v_max

        if is_selected:
            status_code = "selected"
            status_label = "已选中"
            row_class = "is-selected"
            selected_row = idx
        elif not velocity_ok:
            status_code = "warning"
            status_label = "流速不满足"
            row_class = "is-warning"
        else:
            status_code = "normal"
            status_label = "可选"
            row_class = "is-normal"

        rows.append(
            {
                "id": idx,
                "alpha": float(scheme["alpha"]),
                "schemeType": scheme["scheme_type"],
                "b": b_val,
                "h": h_val,
                "beta": float(scheme["beta"]),
                "velocity": velocity,
                "areaIncreasePct": float(scheme["area_increase"]),
                "areaIncreaseLabel": f"+{float(scheme['area_increase']):.0f}%",
                "statusCode": status_code,
                "statusLabel": status_label,
                "rowClass": row_class,
                "isSelected": is_selected,
                "velocityOk": velocity_ok,
            }
        )

    return {
        "columns": columns,
        "rows": rows,
        "selected_row": selected_row,
        "velocity_range": {
            "min": float(v_min),
            "max": float(v_max),
            "label": f"流速约束范围 {float(v_min):g} ~ {float(v_max):g} m/s",
        },
        "summary": {
            "title": "【附录E断面方案对比表】",
            "note": APPENDIX_E_SUMMARY_NOTE,
        },
    }


def appendix_e_shared_head_html() -> str:
    return """
<style>
.appendix-e-card {
    margin: 8px 0 12px 0;
    padding: 18px 20px 16px 20px;
    border-radius: 14px;
    border: 1px solid #E4EBF5;
    background: linear-gradient(180deg, #FFFFFF 0%, #FBFDFF 100%);
    box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
}
.appendix-e-title {
    margin: 0 0 10px 0;
    font-size: 17px;
    font-weight: 700;
    color: #0F4C8A;
    letter-spacing: 0.3px;
}
.appendix-e-note {
    margin: 0 0 14px 0;
    padding: 10px 14px;
    border-radius: 10px;
    background: #F4F8FD;
    color: #355270;
    border: 1px solid #E3ECF8;
    font-size: 13px;
    line-height: 1.75;
}
.appendix-e-meta {
    margin: 14px 0 0 0;
    color: #60758C;
    font-size: 12px;
    line-height: 1.6;
}
.appendix-e-runtime-hint {
    margin: 0 0 10px 0;
    color: #60758C;
    font-size: 12px;
    line-height: 1.6;
}
.appendix-e-runtime-status {
    margin: 0 0 14px 0;
    padding: 14px 16px;
    border-radius: 12px;
    border: 1px solid #DCE7F4;
    background: linear-gradient(180deg, #F7FBFF 0%, #F2F7FD 100%);
    color: #355270;
}
.appendix-e-runtime-status.is-error {
    border-color: #FFD7B0;
    background: linear-gradient(180deg, #FFF9F2 0%, #FFF4E7 100%);
    color: #7A3F00;
}
.appendix-e-runtime-status-title {
    margin: 0 0 6px 0;
    font-size: 14px;
    font-weight: 700;
}
.appendix-e-runtime-status-line {
    margin: 4px 0;
    font-size: 13px;
    line-height: 1.7;
}
.appendix-e-static-table-wrap {
    width: 100%;
    overflow-x: hidden;
    border-radius: 12px;
}
.appendix-e-static-table {
    width: 100%;
    table-layout: fixed;
    border-collapse: separate;
    border-spacing: 0;
    overflow: hidden;
    border: 1px solid #DCE7F4;
    border-radius: 12px;
    background: #FFFFFF;
}
.appendix-e-static-table col.col-alpha {
    width: 7%;
}
.appendix-e-static-table col.col-scheme {
    width: 24%;
}
.appendix-e-static-table col.col-num {
    width: 13%;
}
.appendix-e-static-table col.col-area {
    width: 10%;
}
.appendix-e-static-table col.col-status {
    width: 11%;
}
.appendix-e-static-table th {
    padding: 10px 8px;
    background: linear-gradient(180deg, #EEF5FD 0%, #E6F0FB 100%);
    color: #144B7D;
    border-bottom: 1px solid #DCE7F4;
    font-size: 12px;
    font-weight: 700;
    text-align: center;
    white-space: nowrap;
    line-height: 1.35;
    overflow: hidden;
    text-overflow: ellipsis;
}
.appendix-e-static-table td {
    padding: 9px 8px;
    border-bottom: 1px solid #EEF3F9;
    color: #213547;
    font-size: 12px;
    text-align: center;
    white-space: nowrap;
    line-height: 1.4;
    overflow: hidden;
    text-overflow: ellipsis;
}
.appendix-e-static-table td.text-left {
    text-align: left;
}
.appendix-e-static-table td.num {
    text-align: right;
    font-variant-numeric: tabular-nums;
}
.appendix-e-static-table tr:nth-child(even) td {
    background: #FBFDFF;
}
.appendix-e-static-table tr.is-selected td {
    background: #EAF4FF;
}
.appendix-e-static-table tr.is-warning td {
    background: #FFF5EC;
}
.appendix-e-static-table tr:last-child td {
    border-bottom: none;
}
.appendix-e-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 64px;
    max-width: 100%;
    padding: 3px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.2px;
    line-height: 1.2;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.appendix-e-badge.is-selected {
    color: #0F4C8A;
    background: #D9ECFF;
    border: 1px solid #B8DAFF;
}
.appendix-e-badge.is-warning {
    color: #9A4700;
    background: #FFE7CF;
    border: 1px solid #FFD0A3;
}
.appendix-e-badge.is-normal {
    color: #2C5B85;
    background: #EEF5FD;
    border: 1px solid #D6E5F6;
}
</style>
""".strip()


def appendix_e_tabulator_head_html(asset_root: str = "vendor/tabulator") -> str:
    return (
        f'<link rel="stylesheet" href="{asset_root}/tabulator.min.css">'
        + appendix_e_shared_head_html()
        + """
<style>
.appendix-e-table-shell.is-hidden {
    display: none;
}
.appendix-e-card .tabulator {
    border: 1px solid #DCE7F4;
    border-radius: 12px;
    overflow: hidden;
    background: #FFFFFF;
    font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif;
}
.appendix-e-card .tabulator .tabulator-header {
    background: linear-gradient(180deg, #EEF5FD 0%, #E6F0FB 100%);
    border-bottom: 1px solid #DCE7F4;
}
.appendix-e-card .tabulator .tabulator-header .tabulator-col {
    background: transparent;
    border-right: 1px solid #E3ECF7;
    color: #144B7D;
    font-weight: 700;
    min-height: 40px;
}
.appendix-e-card .tabulator .tabulator-header .tabulator-col .tabulator-col-content {
    padding: 0 6px;
}
.appendix-e-card .tabulator .tabulator-header .tabulator-col .tabulator-col-title {
    white-space: nowrap;
    font-size: 12px;
    line-height: 1.3;
}
.appendix-e-card .tabulator .tabulator-header .tabulator-col:last-child {
    border-right: none;
}
.appendix-e-card .tabulator .tabulator-tableholder {
    overflow-x: hidden;
    overflow-y: auto;
}
.appendix-e-card .tabulator .tabulator-tableholder .tabulator-table {
    background: #FFFFFF;
}
.appendix-e-card .tabulator-row {
    min-height: 38px;
    border-bottom: 1px solid #EEF3F9;
}
.appendix-e-card .tabulator-row:nth-child(even) {
    background: #FBFDFF;
}
.appendix-e-card .tabulator-row.appendix-e-row-selected {
    background: #EAF4FF;
}
.appendix-e-card .tabulator-row.appendix-e-row-warning {
    background: #FFF5EC;
}
.appendix-e-card .tabulator-cell {
    padding: 8px 8px;
    border-right: 1px solid #F0F4F9;
    color: #213547;
    font-size: 12px;
    line-height: 1.4;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.appendix-e-card .tabulator-cell:last-child {
    border-right: none;
}
.appendix-e-card .tabulator-cell.num {
    font-variant-numeric: tabular-nums;
}
</style>
""".strip()
    )


def _render_shell_start(payload, runtime_mode: str | None = None) -> str:
    html_parts = [
        "<section class=\"appendix-e-card\">",
        f"<div class=\"appendix-e-title\">{_e(payload['summary']['title'])}</div>",
        f"<div class=\"appendix-e-note\">{_e(payload['summary']['note'])}</div>",
    ]
    if runtime_mode:
        html_parts.append(
            f"<div class=\"appendix-e-runtime-hint\">渲染模式: {_e(runtime_mode)}</div>"
        )
    return "".join(html_parts)


def _render_shell_end(payload) -> str:
    return f"<div class=\"appendix-e-meta\">注: {_e(payload['velocity_range']['label'])}</div></section>"


def build_appendix_e_static_body(payload, runtime_mode: str | None = None) -> str:
    rows_html = []
    for row in payload["rows"]:
        rows_html.append(
            "<tr class=\"{row_class}\">"
            "<td>{alpha:.2f}</td>"
            "<td class=\"text-left\">{scheme}</td>"
            "<td class=\"num\">{b:.3f}</td>"
            "<td class=\"num\">{h:.3f}</td>"
            "<td class=\"num\">{beta:.3f}</td>"
            "<td class=\"num\">{velocity:.3f}</td>"
            "<td>{area}</td>"
            "<td><span class=\"appendix-e-badge {status_class}\">{status}</span></td>"
            "</tr>".format(
                row_class=_e(row["rowClass"]),
                alpha=row["alpha"],
                scheme=_e(row["schemeType"]),
                b=row["b"],
                h=row["h"],
                beta=row["beta"],
                velocity=row["velocity"],
                area=_e(row["areaIncreaseLabel"]),
                status_class=_e(f"is-{row['statusCode']}"),
                status=_e(row["statusLabel"]),
            )
        )

    return (
        _render_shell_start(payload, runtime_mode=runtime_mode)
        + "<div class=\"appendix-e-static-table-wrap\"><table class=\"appendix-e-static-table\">"
        + "<colgroup>"
        + "<col class=\"col-alpha\"><col class=\"col-scheme\">"
        + "<col class=\"col-num\"><col class=\"col-num\"><col class=\"col-num\"><col class=\"col-num\">"
        + "<col class=\"col-area\"><col class=\"col-status\">"
        + "</colgroup>"
        + "<thead><tr>"
        + "<th>α值</th><th>方案类型</th><th>底宽 B (m)</th><th>水深 h (m)</th>"
        + "<th>宽深比 β</th><th>流速 V (m/s)</th><th>面积增加</th><th>状态</th>"
        + "</tr></thead>"
        + f"<tbody>{''.join(rows_html)}</tbody>"
        + "</table></div>"
        + _render_shell_end(payload)
    )


def build_appendix_e_qt_compatible_body(payload, runtime_mode: str) -> str:
    rows_html = []
    for idx, row in enumerate(payload["rows"], start=1):
        if row["statusCode"] == "selected":
            row_bg = "#EAF4FF"
        elif row["statusCode"] == "warning":
            row_bg = "#FFF5EC"
        elif idx % 2 == 0:
            row_bg = "#FBFDFF"
        else:
            row_bg = "#FFFFFF"

        rows_html.append(
            (
                f"<tr bgcolor=\"{row_bg}\">"
                f"<td align=\"center\">{row['alpha']:.2f}</td>"
                f"<td align=\"left\">{_e(row['schemeType'])}</td>"
                f"<td align=\"right\">{row['b']:.3f}</td>"
                f"<td align=\"right\">{row['h']:.3f}</td>"
                f"<td align=\"right\">{row['beta']:.3f}</td>"
                f"<td align=\"right\">{row['velocity']:.3f}</td>"
                f"<td align=\"center\">{_e(row['areaIncreaseLabel'])}</td>"
                f"<td align=\"center\">{_e(row['statusLabel'])}</td>"
                "</tr>"
            )
        )

    return (
        "<div style=\"margin:8px 0 12px 0; padding:14px 16px; background:#FFFFFF; border:1px solid #DCE7F4;\">"
        f"<p style=\"margin:0 0 10px 0;\"><b>{_e(payload['summary']['title'])}</b></p>"
        f"<p style=\"margin:0 0 10px 0;\">{_e(payload['summary']['note'])}</p>"
        f"<p style=\"margin:0 0 10px 0;\"><font color=\"#60758C\">渲染模式: {_e(runtime_mode)}</font></p>"
        "<table border=\"1\" cellspacing=\"0\" cellpadding=\"6\" width=\"100%\">"
        "<thead><tr bgcolor=\"#EAF3FC\">"
        "<th width=\"8%\">α值</th>"
        "<th width=\"28%\">方案类型</th>"
        "<th width=\"11%\">底宽 B (m)</th>"
        "<th width=\"11%\">水深 h (m)</th>"
        "<th width=\"11%\">宽深比 β</th>"
        "<th width=\"12%\">流速 V (m/s)</th>"
        "<th width=\"9%\">面积增加</th>"
        "<th width=\"10%\">状态</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        "</table>"
        f"<p style=\"margin:10px 0 0 0;\"><font color=\"#60758C\">注: {_e(payload['velocity_range']['label'])}</font></p>"
        "</div>"
    )


def build_appendix_e_error_body(
    payload,
    summary_text: str,
    runtime_mode: str,
    reason_text: str,
    guidance_lines: list[str] | tuple[str, ...],
) -> str:
    detail_lines = [
        f"<div class=\"appendix-e-runtime-status-line\"><b>当前模式:</b> {_e(runtime_mode)}</div>",
        f"<div class=\"appendix-e-runtime-status-line\"><b>失败原因:</b> {_e(summary_text)}</div>",
        f"<div class=\"appendix-e-runtime-status-line\"><b>诊断信息:</b> {_e(reason_text)}</div>",
    ]
    for line in guidance_lines:
        detail_lines.append(
            f"<div class=\"appendix-e-runtime-status-line\">• {_e(line)}</div>"
        )

    return (
        _render_shell_start(payload)
        + "<div class=\"appendix-e-runtime-status is-error\">"
        + "<div class=\"appendix-e-runtime-status-title\">第三方表格未成功渲染</div>"
        + "".join(detail_lines)
        + "</div>"
        + _render_shell_end(payload)
    )


def build_appendix_e_tabulator_body(payload, asset_root: str = "vendor/tabulator") -> str:
    payload_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return f"""
{_render_shell_start(payload)}
  <div id="appendix-e-runtime-status" class="appendix-e-runtime-status">
    <div class="appendix-e-runtime-status-title">正在初始化第三方表格</div>
    <div class="appendix-e-runtime-status-line">正在载入本地 Tabulator 组件并渲染附录E方案对比表。</div>
  </div>
  <div id="appendix-e-table-shell" class="appendix-e-table-shell is-hidden">
    <div id="appendix-e-table"></div>
  </div>
  {_render_shell_end(payload)}
<script src="{asset_root}/tabulator.min.js"></script>
<script>
(function() {{
  const payload = {payload_json};
  const runtimeAttr = "{APPENDIX_E_RUNTIME_ATTR}";
  const readyValue = "{APPENDIX_E_RUNTIME_OK}";
  const errorValue = "{APPENDIX_E_RUNTIME_ERROR}";
  const loadingValue = "{APPENDIX_E_RUNTIME_LOADING}";
  const runtimeCard = document.getElementById("appendix-e-runtime-status");
  const tableShell = document.getElementById("appendix-e-table-shell");
  const body = document.body;

  function setRuntimeState(state, title, lines) {{
    if (body) {{
      body.setAttribute(runtimeAttr, state);
    }}
    window.__appendixETabulatorError = state === errorValue ? (lines || []).join(" | ") : "";
    if (!runtimeCard) {{
      return;
    }}
    runtimeCard.classList.toggle("is-error", state === errorValue);
    runtimeCard.innerHTML =
      '<div class="appendix-e-runtime-status-title">' + title + '</div>' +
      (lines || []).map(function(line) {{
        return '<div class="appendix-e-runtime-status-line">' + line + '</div>';
      }}).join("");
  }}

  function formatNumber(value, precision) {{
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {{
      return "";
    }}
    return numeric.toFixed(precision);
  }}

  function enhanceColumn(col) {{
    const next = Object.assign({{}}, col);
    if (col.kind === "number") {{
      next.formatter = function(cell) {{
        return formatNumber(cell.getValue(), col.precision || 3);
      }};
      next.cssClass = "num";
    }} else if (col.kind === "status") {{
      next.formatter = function(cell) {{
        const row = cell.getRow().getData();
        const code = row.statusCode || "normal";
        const label = row.statusLabel || "";
        return '<span class="appendix-e-badge is-' + code + '">' + label + '</span>';
      }};
    }}
    return next;
  }}

  setRuntimeState(loadingValue, "正在初始化第三方表格", [
    "正在载入本地 Tabulator 组件并渲染附录E方案对比表。"
  ]);

  try {{
    if (typeof Tabulator !== "function") {{
      throw new Error("Tabulator 库未正确加载");
    }}

    const table = new Tabulator("#appendix-e-table", {{
      data: payload.rows,
      layout: "fitDataStretch",
      responsiveLayout: false,
      headerVisible: true,
      height: payload.rows.length > 8 ? "420px" : false,
      placeholder: "暂无附录E方案数据",
      initialSort: [{{ column: "alpha", dir: "asc" }}],
      columnHeaderVertAlign: "middle",
      columns: payload.columns.map(enhanceColumn),
      rowFormatter: function(row) {{
        const el = row.getElement();
        const data = row.getData();
        el.classList.remove("appendix-e-row-selected", "appendix-e-row-warning");
        if (data.rowClass === "is-selected") {{
          el.classList.add("appendix-e-row-selected");
        }} else if (data.rowClass === "is-warning") {{
          el.classList.add("appendix-e-row-warning");
        }}
      }},
    }});

    if (payload.selected_row && payload.rows.length > 8) {{
      const targetRow = table.getRow(payload.selected_row);
      if (targetRow) {{
        targetRow.scrollTo("middle", false);
      }}
    }}

    if (tableShell) {{
      tableShell.classList.remove("is-hidden");
    }}
    if (runtimeCard) {{
      runtimeCard.style.display = "none";
    }}
    setRuntimeState(readyValue, "第三方表格初始化成功", []);
    window.__appendixETabulatorReady = true;
  }} catch (error) {{
    setRuntimeState(errorValue, "第三方表格初始化失败", [
      "附录E未能渲染为 Tabulator 表格。",
      String(error && error.message ? error.message : error)
    ]);
    if (tableShell) {{
      tableShell.classList.add("is-hidden");
    }}
  }}
}})();
</script>
""".strip()
