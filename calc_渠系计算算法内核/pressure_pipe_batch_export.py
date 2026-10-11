# -*- coding: utf-8 -*-
"""消费有压批量数值快照的 CSV、PNG、PDF 导出层；不调用水力求解器。"""

import copy
import os
import numpy as np
from calc_渠系计算算法内核.pressure_pipe_batch_models import (
    BatchCalculationSnapshot, BatchExportOptions, BatchScanResult, PLOT_FLOW_UNIT_M3_PER_S,
)
from calc_渠系计算算法内核.unpressurized_comparison import COMPARISON_COLUMNS


def _safe_savefig(fig, path, **kwargs):
    """保存图片，处理 Windows 文件锁定：若被占用则追加编号另存"""
    try:
        fig.savefig(path, **kwargs)
        return path
    except PermissionError:
        pass
    for attempt in range(1, 100):
        target = _numbered_path(path, attempt)
        try:
            fig.savefig(target, **kwargs)
            return target
        except PermissionError:
            continue
    # 最终回退：带时间戳
    import time
    base, ext = os.path.splitext(path)
    fallback = f"{base}_{int(time.time())}{ext}"
    fig.savefig(fallback, **kwargs)
    return fallback


def _numbered_path(path, n):
    base, ext = os.path.splitext(path)
    return f"{base}_{n}{ext}"


def _setup_adaptive_xaxis(ax, d_data, fontsize=None):
    """自适应X轴：裁剪到数据范围，在数据点D值位置标刻度"""
    d_unique = sorted(set(d_data))
    if not d_unique:
        return
    pad = max(0.05, (d_unique[-1] - d_unique[0]) * 0.03)
    ax.set_xlim(d_unique[0] - pad, d_unique[-1] + pad)
    ax.set_xticks(d_unique)
    labels = [f"{d:.2f}" if abs(d - round(d, 1)) > 1e-9 else f"{d:.1f}"
              for d in d_unique]
    rot = 45 if len(d_unique) > 12 else 0
    ha = 'right' if rot else 'center'
    fs = fontsize or (8 if len(d_unique) > 15 else 9)
    ax.set_xticklabels(labels, fontsize=fs, rotation=rot, ha=ha)
    ax.grid(True, which="major", linestyle="-", linewidth=0.8, alpha=0.5)


def export_batch(snapshot: BatchCalculationSnapshot, options: BatchExportOptions,
                 progress_cb=None, cancel_flag=None) -> BatchScanResult:
    """导出已计算快照；可更换目录或格式重试，不能触发重新计算。"""
    result = BatchScanResult(
        logs=list(snapshot.logs), comparison_rows=copy.deepcopy(list(snapshot.comparison_rows)),
        cancelled=snapshot.cancelled,
    )
    if snapshot.cancelled:
        return result
    if cancel_flag and cancel_flag():
        result.logs.append("用户取消（导出阶段）")
        result.cancelled = True
        return result
    config = options
    output_dir = options.output_dir
    if not output_dir:
        result.logs.append("错误: 未指定输出目录")
        return result
    os.makedirs(output_dir, exist_ok=True)
    import pandas as pd

    results_list = copy.deepcopy(list(snapshot.rows))
    _has_unpr = snapshot.has_unpressurized
    _TOTAL_STEPS, _PHASE1_END, _PHASE2_END = 1000, 300, 950
    if progress_cb:
        progress_cb(_PHASE1_END, _TOTAL_STEPS, "计算完成，保存CSV...")

    if result.comparison_rows and config.output_csv:
        comparison_path = os.path.join(output_dir, "无压输水能力对比明细.csv")
        pd.DataFrame(result.comparison_rows).reindex(columns=COMPARISON_COLUMNS).rename(columns=COMPARISON_COLUMNS).to_csv(
            comparison_path, index=False, encoding="utf-8-sig")
        result.comparison_csv_path = comparison_path
        result.logs.append(f"同流量无压对比明细已保存: {comparison_path}")
    if result.comparison_rows:
        result.logs.append("对比页与专用明细按设计/加大流量分别对齐；原有批量CSV中有压水损仍为加大流量，旧净空标记仅供兼容。")

    df = pd.DataFrame(results_list)
    csv_name = "有压管道批量计算结果.csv"
    csv_path = os.path.join(output_dir, csv_name)
    if config.output_csv:
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        result.csv_path = csv_path
        result.logs.append(f"CSV 已保存: {csv_path}")
    else:
        result.logs.append("已跳过 CSV 输出（配置为关闭）")

    if df.empty:
        result.logs.append("无有效计算数据，跳过绘图")
        return result

    # 如果 PDF 和 PNG 都关闭，则跳过绘图阶段
    if not config.output_pdf_charts and not config.output_subplot_png:
        result.logs.append("已跳过绘图输出（PDF和PNG配置均为关闭）")
        return result

    # 绘图库只在确实需要图表时加载。
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.lines import Line2D
    import seaborn as sns

    sns.set_theme(style="whitegrid")
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'SimSun']
    plt.rcParams['axes.unicode_minus'] = False

    def _percentile_ylim(values, percentile=95, margin=1.2, floor=0.6):
        """沿用既有批量图的分位数坐标范围。"""
        return floor if len(values) == 0 else max(floor, np.percentile(values, percentile) * margin)

    # ---- 阶段2: 绘图 ----
    all_materials = df["管材类型"].unique()

    # 预估绘图总步数
    _chart_total = 0
    for _mn in all_materials:
        _df_m = df[df["管材类型"] == _mn]
        _nq = len(_df_m["Q_target (m³/s)"].unique())
        _chart_total += ((_nq + 9) // 10) * 2  # 图1 + 图2
    _chart_total = max(_chart_total, 1)
    _chart_count = 0
    if progress_cb:
        progress_cb(_PHASE1_END, _TOTAL_STEPS, "开始绘图...")

    for mat_name in all_materials:
        if cancel_flag and cancel_flag():
            result.logs.append("用户取消（绘图阶段）")
            result.cancelled = True
            return result

        df_mat = df[df["管材类型"] == mat_name].copy()

        all_Q = sorted(df_mat["Q_target (m\u00b3/s)"].unique())
        safe_mat = mat_name.replace("(", "_").replace(")", "_").replace("=", "_")

        # -- 图1: 无压/有压流速对比 + 水损双轴 (与 V9 一致) --
        df_unpr_valid = df_mat.dropna(subset=["v_unpr (m/s)"]).copy()
        df_press_valid = df_mat.dropna(subset=["V_press (m/s)", "hf_total_press (m/km)"]).copy()

        if not _has_unpr and (not df_unpr_valid.empty or not df_press_valid.empty):
            # 准备坡度分类
            slope_labels_sorted = sorted(
                [s for s in df_mat["i_unpr_str"].unique()
                 if "/" in s and s not in ("N/A", "n/a")],
                key=lambda s: float(s.split("/")[0]) / float(s.split("/")[1])
            )
            num_slopes = len(slope_labels_sorted)
            palette = sns.color_palette("tab10", n_colors=max(num_slopes, 2))
            markers_list = ['o', 's', 'D', '^', 'v', 'P', 'X', '*', 'h']

            chunk_size = 10
            q_chunks_fig1 = [all_Q[j:j + chunk_size] for j in range(0, len(all_Q), chunk_size)]

            for cidx1, qchunk1 in enumerate(q_chunks_fig1):
                if cancel_flag and cancel_flag():
                    result.logs.append("用户取消（图1）")
                    result.cancelled = True
                    return result

                q_start1 = f"{qchunk1[0]:g}"
                q_end1 = f"{qchunk1[-1]:g}"

                nq1 = len(qchunk1)
                ncol1 = min(5, nq1)
                nrow1 = (nq1 + ncol1 - 1) // ncol1
                fig1 = Figure(figsize=(ncol1 * 7, nrow1 * 5.5))
                FigureCanvasAgg(fig1)
                axes1 = fig1.subplots(nrow1, ncol1, squeeze=False)

                for qi1, q_val1 in enumerate(qchunk1):
                    r1, c1 = divmod(qi1, ncol1)
                    ax1 = axes1[r1][c1]

                    # 绘制无压流速 (按坡度分组)
                    for si_idx, slope_lbl in enumerate(slope_labels_sorted):
                        q_slope_data = df_unpr_valid[
                            (df_unpr_valid["Q_target (m\u00b3/s)"] == q_val1) &
                            (df_unpr_valid["i_unpr_str"] == slope_lbl)
                        ].sort_values("D (m)")
                        if not q_slope_data.empty:
                            ax1.plot(q_slope_data["D (m)"], q_slope_data["v_unpr (m/s)"],
                                     color=palette[si_idx % num_slopes],
                                     marker=markers_list[si_idx % len(markers_list)],
                                     markersize=4, linewidth=1.3, label=slope_lbl if qi1 == 0 else "_nolegend_")

                    # 绘制有压流速 (与坡度无关，去重)
                    q_press_data = df_press_valid[
                        df_press_valid["Q_target (m\u00b3/s)"] == q_val1
                    ].drop_duplicates(subset=["D (m)"]).sort_values("D (m)")
                    if not q_press_data.empty:
                        ax1.plot(q_press_data["D (m)"], q_press_data["V_press (m/s)"],
                                 linestyle=":", color="dimgray", linewidth=1.8, marker=".", markersize=5,
                                 label="V_press (有压)" if qi1 == 0 else "_nolegend_")

                    # y轴范围 (P95自适应)
                    _all_v = []
                    q_unpr_v = df_unpr_valid[df_unpr_valid["Q_target (m\u00b3/s)"] == q_val1]["v_unpr (m/s)"].dropna()
                    if not q_unpr_v.empty:
                        _all_v.extend(q_unpr_v.tolist())
                    if not q_press_data.empty:
                        _all_v.extend(q_press_data["V_press (m/s)"].dropna().tolist())
                    ax1.set_ylim(bottom=0, top=_percentile_ylim(_all_v, floor=0.6))

                    # 右轴: 有压总水损
                    ax2_1 = ax1.twinx()
                    if not q_press_data.empty:
                        hf_color = "firebrick"
                        ax2_1.plot(q_press_data["D (m)"], q_press_data["hf_total_press (m/km)"],
                                   linestyle="--", color=hf_color, linewidth=1.8, marker="x", markersize=4,
                                   alpha=0.8, label="总水损 (右轴)" if qi1 == 0 else "_nolegend_")
                        _d_med = q_press_data["D (m)"].median()
                        _hf_upper = q_press_data.loc[q_press_data["D (m)"] >= _d_med, "hf_total_press (m/km)"].dropna().tolist()
                        ax2_1.set_ylim(bottom=0, top=_percentile_ylim(_hf_upper, floor=0.5))
                        ax2_1.set_ylabel("总水头损失 (m/km)", color=hf_color)
                        ax2_1.tick_params(axis="y", labelcolor=hf_color)
                    else:
                        ax2_1.set_yticks([])

                    ax1.set_xlabel("水力计算内径 (m)")
                    ax1.set_ylabel("流速 (m/s)")
                    ax1.set_title(f"Q = {q_val1:g} {PLOT_FLOW_UNIT_M3_PER_S}")
                    # 自适应X轴
                    _d_q1 = set(df_unpr_valid[df_unpr_valid["Q_target (m\u00b3/s)"] == q_val1]["D (m)"].tolist())
                    if not q_press_data.empty:
                        _d_q1.update(q_press_data["D (m)"].tolist())
                    _setup_adaptive_xaxis(ax1, list(_d_q1))

                # 隐藏多余子图
                for qi1 in range(nq1, nrow1 * ncol1):
                    r1, c1 = divmod(qi1, ncol1)
                    axes1[r1][c1].set_visible(False)

                fig1.suptitle(
                    f"图1: 无压/有压流速与总水损对比 "
                    f"(Q: {q_start1}-{q_end1} {PLOT_FLOW_UNIT_M3_PER_S}, {mat_name})",
                    fontsize=14,
                )
                fig1.tight_layout(rect=[0, 0, 1, 0.95])

                pdf_name1 = f"图1_流速水损对比_{q_start1}_{q_end1}_{safe_mat}.pdf"
                pdf_path1 = os.path.join(output_dir, pdf_name1)
                if config.output_pdf_charts:
                    actual1 = _safe_savefig(fig1, pdf_path1, dpi=150)
                    result.generated_pdfs.append(actual1)
                    result.logs.append(f"PDF: {os.path.basename(actual1)}")

                _chart_count += 1
                if progress_cb:
                    progress_cb(
                        _PHASE1_END + int(_chart_count / _chart_total * ((900 if _has_unpr else _PHASE2_END) - _PHASE1_END)),
                        _TOTAL_STEPS,
                        f"绘图中 ({_chart_count}/{_chart_total}) {pdf_name1}",
                    )

                # 子图 PNG - 为每个Q值创建独立完整的figure
                if config.output_subplot_png:
                    png_dir1 = os.path.join(output_dir, "子图PNG", safe_mat)
                    os.makedirs(png_dir1, exist_ok=True)
                    for qi1, q_val1 in enumerate(qchunk1):
                        # 创建独立figure
                        fig_sub1 = Figure(figsize=(10, 7))
                        FigureCanvasAgg(fig_sub1)
                        ax_sub1 = fig_sub1.add_subplot(111)
                        ax_sub1_twin = ax_sub1.twinx()

                        ax_sub1.set_xlabel("水力计算内径 (m)", fontsize=12)

                        # 绘制无压流速 (按坡度分组)
                        _all_v_sub1 = []
                        for si_idx, slope_lbl in enumerate(slope_labels_sorted):
                            q_slope_data = df_unpr_valid[
                                (df_unpr_valid["Q_target (m\u00b3/s)"] == q_val1) &
                                (df_unpr_valid["i_unpr_str"] == slope_lbl)
                            ].sort_values("D (m)")
                            if not q_slope_data.empty:
                                ax_sub1.plot(q_slope_data["D (m)"], q_slope_data["v_unpr (m/s)"],
                                            color=palette[si_idx % num_slopes],
                                            marker=markers_list[si_idx % len(markers_list)],
                                            markersize=4, linewidth=1.3, label=f"i={slope_lbl} (无压)")
                                _all_v_sub1.extend(q_slope_data["v_unpr (m/s)"].dropna().tolist())

                        # 绘制有压流速
                        q_press_data_sub1 = df_press_valid[
                            df_press_valid["Q_target (m\u00b3/s)"] == q_val1
                        ].drop_duplicates(subset=["D (m)"]).sort_values("D (m)")
                        if not q_press_data_sub1.empty:
                            ax_sub1.plot(q_press_data_sub1["D (m)"], q_press_data_sub1["V_press (m/s)"],
                                        linestyle=":", color="dimgray", linewidth=1.8, marker=".", markersize=5,
                                        label="V_press (有压)")
                            _all_v_sub1.extend(q_press_data_sub1["V_press (m/s)"].dropna().tolist())

                        # 设置左Y轴 (P95自适应)
                        ax_sub1.set_ylabel("流速 (m/s)", fontsize=12)
                        ax_sub1.set_ylim(bottom=0, top=_percentile_ylim(_all_v_sub1, floor=0.6))

                        # 绘制右轴: 有压总水损
                        hf_color_sub1 = "firebrick"
                        if not q_press_data_sub1.empty:
                            ax_sub1_twin.plot(q_press_data_sub1["D (m)"], q_press_data_sub1["hf_total_press (m/km)"],
                                             linestyle="--", color=hf_color_sub1, linewidth=1.8, marker="x", markersize=4,
                                             alpha=0.8, label="总水损 (有压, 右轴)")
                            _d_med_sub1 = q_press_data_sub1["D (m)"].median()
                            _hf_upper_sub1 = q_press_data_sub1.loc[q_press_data_sub1["D (m)"] >= _d_med_sub1, "hf_total_press (m/km)"].dropna().tolist()
                            ax_sub1_twin.set_ylim(bottom=0, top=_percentile_ylim(_hf_upper_sub1, floor=0.5))
                            ax_sub1_twin.set_ylabel("总水头损失 (m/km)", fontsize=11, color=hf_color_sub1)
                            ax_sub1_twin.tick_params(axis="y", labelcolor=hf_color_sub1)
                            ax_sub1_twin.spines["right"].set_edgecolor(hf_color_sub1)
                        else:
                            ax_sub1_twin.set_yticks([])

                        # 自适应X轴
                        _d_sub1 = set(df_unpr_valid[df_unpr_valid["Q_target (m\u00b3/s)"] == q_val1]["D (m)"].tolist())
                        if not q_press_data_sub1.empty:
                            _d_sub1.update(q_press_data_sub1["D (m)"].tolist())
                        _setup_adaptive_xaxis(ax_sub1, list(_d_sub1), fontsize=10)

                        # 设置标题
                        fig_sub1.suptitle(
                            f"图1: 无压/有压流速与总水损对比\n"
                            f"目标流量 Q = {q_val1:g} {PLOT_FLOW_UNIT_M3_PER_S}, 管材: {mat_name}",
                            fontsize=14,
                            y=0.98,
                        )

                        # 合并图例
                        handles_sub1, labels_sub1 = ax_sub1.get_legend_handles_labels()
                        handles_twin1, labels_twin1 = ax_sub1_twin.get_legend_handles_labels()
                        fig_sub1.legend(handles_sub1 + handles_twin1, labels_sub1 + labels_twin1,
                                       loc='upper right', bbox_to_anchor=(0.98, 0.88),
                                       fontsize=8, frameon=True, ncol=2)

                        # 保存
                        fig_sub1.tight_layout(rect=[0, 0, 1, 0.93])
                        png_name1 = f"图1_Q{q_val1:g}_{safe_mat}.png"
                        png_path1 = os.path.join(png_dir1, png_name1)
                        actual_png1 = _safe_savefig(fig_sub1, png_path1, dpi=300, bbox_inches='tight', pad_inches=0.1)
                        result.generated_pngs.append(actual_png1)
                        plt.close(fig_sub1)

                plt.close(fig1)

        # -- 图2: 经济/妥协设计点 --
        df_press = df_mat.dropna(subset=["V_press (m/s)", "hf_total_press (m/km)"]).copy()
        df_press = df_press[["Q_target (m\u00b3/s)", "D (m)", "V_press (m/s)",
                             "hf_total_press (m/km)"]].drop_duplicates()
        df_press["category"] = pd.Series(dtype="object")
        cond_eco = (
            (df_press["V_press (m/s)"] >= 0.9)
            & (df_press["V_press (m/s)"] <= 1.5)
            & (df_press["hf_total_press (m/km)"] <= 5.0)
        )
        cond_comp = (
            (df_press["V_press (m/s)"] >= 0.6)
            & (df_press["V_press (m/s)"] < 0.9)
            & (df_press["hf_total_press (m/km)"] <= 5.0)
        )
        df_press.loc[cond_eco, "category"] = "经济流速 (0.9-1.5 m/s, 总hf <= 5 m/km)"
        df_press.loc[cond_comp, "category"] = "妥协流速 (0.6-0.89 m/s, 总hf <= 5 m/km)"
        df_cat = df_press.dropna(subset=["category"]).copy()

        if not df_cat.empty:
            chunk_size = 10
            q_cat_vals = sorted(df_cat["Q_target (m\u00b3/s)"].unique())
            q_chunks = [q_cat_vals[i:i + chunk_size] for i in range(0, len(q_cat_vals), chunk_size)]

            for cidx, qchunk in enumerate(q_chunks):
                if cancel_flag and cancel_flag():
                    result.logs.append("用户取消（绘图）")
                    result.cancelled = True
                    return result

                q_start = f"{qchunk[0]:g}"
                q_end = f"{qchunk[-1]:g}"

                df_chunk = df_cat[df_cat["Q_target (m\u00b3/s)"].isin(qchunk)].copy()
                if df_chunk.empty:
                    continue

                nq = len(qchunk)
                ncol = min(5, nq)
                nrow = (nq + ncol - 1) // ncol
                fig = Figure(figsize=(ncol * 7, nrow * 5.5))
                FigureCanvasAgg(fig)
                axes = fig.subplots(nrow, ncol, squeeze=False)

                color_v = "#1976D2"
                color_hf = "darkorange"

                for qi, q_val in enumerate(qchunk):
                    r, c = divmod(qi, ncol)
                    ax1 = axes[r][c]
                    ax2 = ax1.twinx()

                    q_data = df_chunk[df_chunk["Q_target (m\u00b3/s)"] == q_val]
                    if q_data.empty:
                        ax1.text(0.5, 0.5, "无数据", ha="center", va="center", transform=ax1.transAxes)
                        continue

                    for _, row in q_data.iterrows():
                        is_eco = "经济" in row["category"]
                        fc_v = color_v if is_eco else "none"
                        fc_h = color_hf if is_eco else "none"
                        lw = 0.6 if is_eco else 1.8
                        ax1.scatter(row["D (m)"], row["V_press (m/s)"], marker="o", s=70,
                                    facecolors=fc_v, edgecolors=color_v, linewidths=lw, alpha=0.85, zorder=5)
                        ax1.text(row["D (m)"] + 0.015, row["V_press (m/s)"],
                                 f" {row['V_press (m/s)']:.2f}", fontsize=6.5, color=color_v, fontweight="bold", va="center")
                        ax2.scatter(row["D (m)"], row["hf_total_press (m/km)"], marker="o", s=70,
                                    facecolors=fc_h, edgecolors=color_hf, linewidths=lw, alpha=0.85, zorder=5)
                        ax2.text(row["D (m)"] - 0.015, row["hf_total_press (m/km)"],
                                 f" {row['hf_total_press (m/km)']:.2f} ", fontsize=6.5, color=color_hf, fontstyle="italic", va="center", ha="right")

                    ax1.set_ylim(0.5, 1.8)
                    ax2.set_ylim(0, 5.5)
                    ax1.set_xlabel("水力计算内径 (m)")
                    ax1.set_ylabel("流速 V (m/s)", color=color_v)
                    ax2.set_ylabel("总水头损失 (m/km)", color=color_hf)
                    ax1.tick_params(axis="y", labelcolor=color_v)
                    ax2.tick_params(axis="y", labelcolor=color_hf)
                    ax1.set_title(f"Q = {q_val:g} {PLOT_FLOW_UNIT_M3_PER_S}")
                    _setup_adaptive_xaxis(ax1, q_data["D (m)"].tolist())

                # 隐藏多余子图
                for qi in range(nq, nrow * ncol):
                    r, c = divmod(qi, ncol)
                    axes[r][c].set_visible(False)

                fig.suptitle(
                    f"有压管道优选设计点 "
                    f"(Q: {q_start}-{q_end} {PLOT_FLOW_UNIT_M3_PER_S}, {mat_name})",
                    fontsize=14,
                )
                fig.tight_layout(rect=[0, 0, 1, 0.95])

                pdf_name = f"图2_优选设计点_{q_start}_{q_end}_{safe_mat}.pdf"
                pdf_path = os.path.join(output_dir, pdf_name)
                if config.output_pdf_charts:
                    actual2 = _safe_savefig(fig, pdf_path, dpi=150)
                    result.generated_pdfs.append(actual2)
                    result.logs.append(f"PDF: {os.path.basename(actual2)}")

                _chart_count += 1
                if progress_cb:
                    progress_cb(
                        _PHASE1_END + int(_chart_count / _chart_total * ((900 if _has_unpr else _PHASE2_END) - _PHASE1_END)),
                        _TOTAL_STEPS,
                        f"绘图中 ({_chart_count}/{_chart_total}) {pdf_name}",
                    )

                # 子图 PNG - 为每个Q值创建独立完整的figure
                if config.output_subplot_png:
                    png_dir = os.path.join(output_dir, "子图PNG", safe_mat)
                    os.makedirs(png_dir, exist_ok=True)
                    for qi, q_val in enumerate(qchunk):
                        # 筛选当前Q值的数据
                        q_data_sub = df_chunk[df_chunk["Q_target (m\u00b3/s)"] == q_val]
                        if q_data_sub.empty:
                            continue

                        # 创建独立figure
                        fig_sub2 = Figure(figsize=(10, 7))
                        FigureCanvasAgg(fig_sub2)
                        ax_sub2 = fig_sub2.add_subplot(111)
                        ax_sub2_twin = ax_sub2.twinx()

                        ax_sub2.set_xlabel("水力计算内径 (m)", fontsize=12)

                        # 绘制散点
                        color_v_sub2 = "#1976D2"
                        color_hf_sub2 = "darkorange"

                        for _, row in q_data_sub.iterrows():
                            is_eco = "经济" in row["category"]
                            fc_v = color_v_sub2 if is_eco else "none"
                            fc_h = color_hf_sub2 if is_eco else "none"
                            lw = 0.6 if is_eco else 1.8

                            # 流速散点（左Y轴）
                            ax_sub2.scatter(row["D (m)"], row["V_press (m/s)"], marker="o", s=80,
                                           facecolors=fc_v, edgecolors=color_v_sub2, linewidths=lw, alpha=0.85, zorder=5)
                            ax_sub2.text(row["D (m)"] + 0.02, row["V_press (m/s)"],
                                        f" {row['V_press (m/s)']:.2f}m/s", fontsize=8, color=color_v_sub2,
                                        fontweight="bold", va="center")

                            # 水头损失散点（右Y轴）
                            ax_sub2_twin.scatter(row["D (m)"], row["hf_total_press (m/km)"], marker="o", s=80,
                                                facecolors=fc_h, edgecolors=color_hf_sub2, linewidths=lw, alpha=0.85, zorder=5)
                            ax_sub2_twin.text(row["D (m)"] - 0.02, row["hf_total_press (m/km)"],
                                             f" {row['hf_total_press (m/km)']:.2f}m/km ", fontsize=8, color=color_hf_sub2,
                                             fontstyle="italic", va="center", ha="right")

                        # 设置左Y轴
                        ax_sub2.set_ylim(0.5, 1.8)
                        ax_sub2.set_ylabel("流速 V (m/s)", fontsize=12, color=color_v_sub2)
                        ax_sub2.tick_params(axis="y", labelcolor=color_v_sub2)
                        ax_sub2.spines["left"].set_edgecolor(color_v_sub2)
                        ax_sub2.spines["left"].set_linewidth(1.5)

                        # 设置右Y轴
                        ax_sub2_twin.set_ylim(0, 5.5)
                        ax_sub2_twin.set_ylabel("总水头损失 (m/km)", fontsize=11, color=color_hf_sub2)
                        ax_sub2_twin.tick_params(axis="y", labelcolor=color_hf_sub2)
                        ax_sub2_twin.spines["right"].set_edgecolor(color_hf_sub2)
                        ax_sub2_twin.spines["right"].set_linewidth(1.5)

                        # 自适应X轴
                        _setup_adaptive_xaxis(ax_sub2, q_data_sub["D (m)"].tolist(), fontsize=10)

                        # 设置标题
                        fig_sub2.suptitle(
                            f"图2: 有压管道优选设计点\n"
                            f"目标流量 Q = {q_val:g} {PLOT_FLOW_UNIT_M3_PER_S}, 管材: {mat_name}",
                            fontsize=14,
                            y=0.98,
                        )

                        # 创建图例
                        handles_sub2 = [
                            Line2D([0], [0], marker="o", color="w",
                                  markerfacecolor=color_v_sub2, markeredgecolor=color_v_sub2,
                                  markersize=8, linestyle="None", mew=0.6, label="经济区 流速 (实心蓝)"),
                            Line2D([0], [0], marker="o", color="w",
                                  markerfacecolor=color_hf_sub2, markeredgecolor=color_hf_sub2,
                                  markersize=8, linestyle="None", mew=0.6, label="经济区 总水损 (实心橙)"),
                            Line2D([0], [0], marker="o", color="w",
                                  markerfacecolor="none", markeredgecolor=color_v_sub2,
                                  markersize=8, linestyle="None", mew=1.8, label="妥协区 流速 (空心蓝)"),
                            Line2D([0], [0], marker="o", color="w",
                                  markerfacecolor="none", markeredgecolor=color_hf_sub2,
                                  markersize=8, linestyle="None", mew=1.8, label="妥协区 总水损 (空心橙)")
                        ]
                        fig_sub2.legend(handles=handles_sub2, loc='upper right',
                                       bbox_to_anchor=(0.98, 0.88), fontsize=9, frameon=True, ncol=2)

                        # 保存
                        fig_sub2.tight_layout(rect=[0, 0, 1, 0.93])
                        png_name = f"图2_Q{q_val:g}_{safe_mat}.png"
                        png_path = os.path.join(png_dir, png_name)
                        actual_png2 = _safe_savefig(fig_sub2, png_path, dpi=300, bbox_inches='tight', pad_inches=0.1)
                        result.generated_pngs.append(actual_png2)
                        plt.close(fig_sub2)

                plt.close(fig)

    if _has_unpr:
        from calc_渠系计算算法内核.unpressurized_plots import export_comparison_charts
        if not export_comparison_charts(result.comparison_rows, config, result, _safe_savefig, progress_cb, cancel_flag):
            result.cancelled = True
            return result

    # ---- 阶段3: 合并 PDF ----
    if progress_cb:
        progress_cb(_PHASE2_END, _TOTAL_STEPS, "合并PDF文件...")
    if config.output_merged_pdf and result.generated_pdfs:
        try:
            from pypdf import PdfWriter
            merger = PdfWriter()
            for p in sorted(result.generated_pdfs):
                merger.append(p)
            merged_name = "合并图表_有压管道批量计算.pdf"
            merged_path = os.path.join(output_dir, merged_name)
            with open(merged_path, "wb") as fout:
                merger.write(fout)
            merger.close()
            result.merged_pdf = merged_path
            result.logs.append(f"合并PDF: {merged_path}")
        except ImportError:
            result.logs.append("警告: pypdf 未安装，跳过PDF合并")
        except Exception as e:
            result.logs.append(f"合并PDF失败: {e}")
    elif not config.output_merged_pdf:
        result.logs.append("已跳过 合并PDF 输出（配置为关闭）")

    if progress_cb:
        progress_cb(_TOTAL_STEPS, _TOTAL_STEPS, "批量计算完成")

    return result


# ============================================================
# 5. 内部辅助
# ============================================================
