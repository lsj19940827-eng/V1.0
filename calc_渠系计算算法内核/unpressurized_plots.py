"""无压对比图表，从计算快照生成批量 PDF/PNG，完整数据保留在 CSV。"""

import os
import re
from collections import defaultdict

from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties

from .unpressurized_comparison import FLOW_BASES, preferred_diameter

FLOW_UNIT = r"m$^3$/s"
COLORS = ("#0078d4", "#e07820")


def _wrap_plot_text(text, renderer, properties, width):
    """按实际字体宽度换行，保留数学单位整体，避免中文长规格被裁切。"""
    lines = []
    for paragraph in text.splitlines():
        line = ""
        for token in re.findall(r"\$[^$]*\$|.", paragraph):
            candidate = line + token
            measured = renderer.get_text_width_height_descent(
                candidate, properties, ismath="$" in candidate)[0]
            if line and measured > width:
                lines.append(line.rstrip())
                line = token.lstrip()
            else:
                line = candidate
        lines.append(line)
    return "\n".join(lines)


class _ComparisonFigure(Figure):
    """在窗口缩放及导出时重新排版，使用各自渲染器的字体尺寸。"""

    def draw(self, renderer):
        """先按画布宽度安排标题和刻度，再由约束布局分配上下留白。"""
        # Qt 切换规格时旧画布可能仍有排队的重绘，清空后交给基类处理。
        if not self.axes:
            return super().draw(renderer)
        padding = renderer.points_to_pixels(16)
        width = self.bbox.width - 2 * padding
        for artist, original in self.comparison_texts:
            artist.set_text(_wrap_plot_text(original, renderer, artist.get_fontproperties(), width))
        axis = self.axes[-1]
        slopes = self.comparison_slopes
        labels = [f"1/{value}" for value in slopes]
        properties = FontProperties(family="DejaVu Sans", size=9)
        label_width = max(renderer.get_text_width_height_descent(
            label, properties, ismath=False)[0] for label in labels)
        # 保守预留纵轴和两端空间；抽稀只影响标签，不改变方案或曲线数据。
        plot_width = self.bbox.width * 0.70
        max_labels = max(2, int(plot_width / (label_width + padding)))
        count = min(len(slopes), max_labels)
        indexes = ([0] if count == 1 else
                   sorted({round(i * (len(slopes) - 1) / (count - 1)) for i in range(count)}))
        axis.set_xticks(indexes, [labels[index] for index in indexes],
                        fontsize=9, fontfamily="DejaVu Sans")
        for subplot in self.axes:
            legend = subplot.get_legend()
            labels_width = sum(renderer.get_text_width_height_descent(
                text.get_text(), text.get_fontproperties(), ismath=False)[0]
                for text in legend.get_texts())
            legend.set_ncols(1 if labels_width / 2 + 6 * padding > plot_width else 2)
        super().draw(renderer)


def comparison_figure(rows, *, compact=False):
    """为同一管材、设计流量和管径绘制能力、充满度及同流量流速对比。"""
    fig = _ComparisonFigure(figsize=(10, 6.5) if compact else (12, 8), constrained_layout=True)
    fig.set_facecolor("white")
    axes = fig.subplots(3, 1, sharex=True)
    first = rows[0]
    slopes = sorted({row["denominator"] for row in rows})
    positions = {value: index for index, value in enumerate(slopes)}
    font = {"fontfamily": ["Microsoft YaHei", "SimHei", "DejaVu Sans"]}
    for index, basis in enumerate(FLOW_BASES):
        subset = sorted((row for row in rows if row["basis"] == basis), key=lambda row: row["denominator"])
        if not subset:
            continue
        x = [positions[row["denominator"]] for row in subset]
        if index == 0:
            axes[0].plot(x, [row["capacity"] for row in subset], "o-", color="#14866d", label="模型最大无压流量")
        axes[0].axhline(subset[0]["flow"], color=COLORS[index], linestyle="--", label=basis)
        # 缺解位置用 NaN 断开，不将无解点与远端可解点连成连续曲线。
        no_solution = all(row['depth'] is None for row in subset)
        label = basis + ('（无有效解）' if no_solution else '')
        axes[1].plot(x, [float("nan") if row["filling"] is None else row["filling"] * 100 for row in subset],
                     "o-", color=COLORS[index], label=label)
        axes[2].plot(x, [float("nan") if row["velocity"] is None else row["velocity"] for row in subset],
                     "o-", color=COLORS[index], label=f"{label} · 无压")
        axes[2].axhline(subset[0]["pressure_velocity"], color=COLORS[index], linestyle=":", label=f"{basis} · 有压")
    for axis, title in zip(axes, (f"输水能力 ({FLOW_UNIT})", "充满度 (%)", "流速 (m/s)")):
        axis.set_ylabel(title, fontsize=10, **font)
        axis.grid(alpha=0.22)
        axis.legend(loc="best", prop={"family": font["fontfamily"], "size": 8}, ncol=2)
        for tick in axis.get_yticklabels():
            tick.set_fontfamily("DejaVu Sans")
    fig.comparison_slopes = slopes
    xlabel = axes[2].set_xlabel("管道底坡（按分母递增排列，等间距仅表示不同方案）", fontsize=9, **font)
    axes[1].set_ylim(bottom=0, top=100)
    title = (f"无压输水能力对比 · {first['material']}\n"
             f"{first['specification']}\n水力内径 {first['diameter']:.4f} m · "
             f"设计流量 {first['design_flow']:g} {FLOW_UNIT} · 糙率 {first['roughness']:g}")
    heading = fig.suptitle(title, fontsize=11, **font)
    note = fig.supxlabel('圆管无压均匀流，采用较浅水深支；曲线空缺表示没有有效水深解，项目净空判定见对比明细。',
                        fontsize=8, **font)
    fig.comparison_texts = [(artist, artist.get_text()) for artist in (heading, xlabel, note)]
    return fig


def export_comparison_charts(rows, config, result, savefig, progress_cb=None, cancel_flag=None):
    """每组管材/流量输出默认候选的对比图，全部管径保留在界面及明细 CSV。"""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    groups = defaultdict(list)
    for row in rows:
        groups[(row["material"], row["design_flow"])].append(row)
    for index, ((material, flow), group) in enumerate(groups.items()):
        if cancel_flag and cancel_flag():
            result.logs.append("用户取消（无压对比图表阶段）")
            return False
        diameter = preferred_diameter(group)
        selected = [row for row in group if row["diameter"] == diameter]
        fig = comparison_figure(selected)
        FigureCanvasAgg(fig)
        safe_material = "".join("_" if char in '<>:"/\\|?*' else char for char in material)
        name = f"无压输水能力_{safe_material}_Q{flow:g}"
        if config.output_pdf_charts:
            path = savefig(fig, os.path.join(config.output_dir, name + ".pdf"), bbox_inches="tight")
            result.generated_pdfs.append(path)
        if config.output_subplot_png:
            path = savefig(fig, os.path.join(config.output_dir, name + ".png"), dpi=180, bbox_inches="tight")
            result.generated_pngs.append(path)
        fig.clear()
        if progress_cb:
            progress_cb(920 + int((index + 1) / len(groups) * 25), 1000,
                        f"无压对比图 {index + 1}/{len(groups)}：{material}，设计流量 {flow:g}")
    result.logs.append("无压图表展示可用底坡最多的最小规格；全无可用结果时展示扫描上限。全部管径、底坡与工况的完整数值见无压对比明细 CSV。")
    return True
