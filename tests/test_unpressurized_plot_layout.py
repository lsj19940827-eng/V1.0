"""无压对比图的实际渲染边界回归，覆盖窄窗口、缩放及长规格。"""

import io

import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg

from calc_渠系计算算法内核.unpressurized_plots import comparison_figure


def _rows(slopes):
    """构造截图中的长 PE 规格和两组无解工况，只检查图表展示。"""
    return [dict(material="聚乙烯（PE）管",
                 specification="PE100 DN450×26.7 mm，SDR17，PN1 MPa，名义计算内径 di=396.6 mm",
                 diameter=.3966, design_flow=.2, roughness=.014,
                 denominator=slope, basis=basis, capacity=.09 * (500 / slope) ** .5,
                 flow=flow, depth=None, filling=None, velocity=None,
                 pressure_velocity=flow / .1235)
            for basis, flow in (("设计流量", .2), ("加大流量", .26)) for slope in slopes]


@pytest.mark.parametrize("width,dpi,slopes", [
    (640, 100, range(500, 3001, 250)),
    (1000, 100, range(500, 3001, 250)),
    (640, 150, range(500, 3001, 250)),
    (640, 100, range(500, 10001, 50)),
    (640, 100, [500]),
])
def test_labels_fit_after_resize(width, dpi, slopes):
    """从宽图缩到实际视区后，文字完整、刻度不相交且数据没有抽稀。"""
    slopes = list(slopes)
    figure = comparison_figure(_rows(slopes), compact=True)
    canvas = FigureCanvasAgg(figure)
    canvas.draw()
    figure.set_dpi(dpi)
    figure.set_size_inches(width / 100, 7)
    canvas.draw()
    renderer = canvas.get_renderer()
    for artist, _ in figure.comparison_texts:
        box = artist.get_window_extent(renderer)
        assert box.x0 >= 0 and box.x1 <= figure.bbox.width
        assert box.y0 >= 0 and box.y1 <= figure.bbox.height
    ticks = figure.axes[-1].get_xticklabels()
    boxes = [tick.get_window_extent(renderer) for tick in ticks]
    assert all(left.x1 + 4 < right.x0 for left, right in zip(boxes, boxes[1:]))
    assert ticks[0].get_text() == f"1/{slopes[0]}"
    assert ticks[-1].get_text() == f"1/{slopes[-1]}"
    assert len(figure.axes[0].lines[0].get_xdata()) == len(slopes)
    assert figure._suptitle.get_window_extent(renderer).y0 > figure.axes[0].bbox.y1
    assert figure.axes[-1].xaxis.label.get_window_extent(renderer).y1 < min(box.y0 for box in boxes)
    for axis in figure.axes:
        box = axis.get_legend().get_window_extent(renderer)
        assert box.x0 >= 0 and box.x1 <= figure.bbox.width


@pytest.mark.parametrize("format", ["png", "pdf"])
def test_export_uses_responsive_layout(format):
    """位图和 PDF 渲染器均能排版完整长标题并成功输出。"""
    figure = comparison_figure(_rows(range(500, 3001, 250)))
    FigureCanvasAgg(figure)
    output = io.BytesIO()
    figure.savefig(output, format=format, dpi=150, bbox_inches="tight")
    assert output.tell() > 1000
