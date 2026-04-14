# -*- coding: utf-8 -*-
"""暗涵断面 DXF 导出。"""
import math
from app_渠系计算前端.dxf_common import (
    _add_dim_h,
    _add_dim_v,
    _add_text_block,
    add_case_title,
    ensure_tracked_msp,
    setup_section_dxf_document,
)
from app_渠系计算前端.tunnel.geometry import (
    arch_half_width,
    build_arch_geometry,
    build_arch_outline_polyline,
)


def _normalize_culvert_section_type(value):
    """统一暗涵断面类型口径，兼容旧的家族前缀写法。"""
    text = str(value or "").strip()
    if text in {"圆拱直墙型", "圆拱直墙型暗涵", "暗涵圆拱直墙型", "暗涵-圆拱直墙型", "隧洞-圆拱直墙型"}:
        return "圆拱直墙型"
    return "矩形"


def export_culvert_dxf(filepath, result, input_params, scale_denom=100):
    try:
        import ezdxf
    except ImportError:
        raise ImportError("需要安装 ezdxf 库: pip install ezdxf")
    doc = ezdxf.new('R2010')
    setup_section_dxf_document(doc, scale_denom=scale_denom)
    draw_culvert_dxf_on_msp(
        doc.modelspace(),
        result,
        input_params,
        scale_denom=scale_denom,
    )
    doc.saveas(filepath)


def draw_culvert_dxf_on_msp(
    msp,
    result,
    input_params,
    scale_denom=100,
    layer_prefix="",
    title="",
):
    tracked_msp = ensure_tracked_msp(msp, layer_prefix=layer_prefix)
    section_type = _normalize_culvert_section_type(input_params.get("section_type", "矩形"))
    sf = 1000.0 / scale_denom
    if section_type == "圆拱直墙型":
        _draw_arch_culvert(tracked_msp, result, input_params, sf, scale_denom)
    else:
        _draw_rect_culvert(tracked_msp, result, input_params, sf, scale_denom)
    if title:
        add_case_title(tracked_msp, title)
    return tracked_msp.size()


def _draw_rect_culvert(msp, result, p, sf=1.0, scale_denom=100):
    Q  = p.get('Q', 0.0); n = p.get('n', 0.014); si = p.get('slope_inv', 3000.0)
    B  = result.get('B', 0.0); H = result.get('H', 0.0)
    h_d   = result.get('h_design', 0.0);  V_d   = result.get('V_design', 0.0)
    A_d   = result.get('A_design', 0.0)
    fb_d  = result.get('freeboard_hgt_design', H - h_d)
    Q_inc = result.get('Q_increased', 0.0); h_inc = result.get('h_increased', 0.0)
    V_inc = result.get('V_increased', 0.0)
    fb_inc = result.get('freeboard_hgt_inc', H - h_inc)
    inc   = result.get('increase_percent', 0.0)
    BH    = result.get('BH_ratio', B/h_d if h_d else 0)
    is_opt = result.get('is_optimal_section', False)

    char = max(B, H, 1.0)*sf; th = 3.5; ar = th*0.85; gap = char*0.18

    # 1. 封闭矩形轮廓（暗涵有顶板，实线）
    segs = [
        ((-B/2*sf, 0),    (B/2*sf, 0)),
        ((-B/2*sf, 0),    (-B/2*sf, H*sf)),
        ((B/2*sf,  0),    (B/2*sf,  H*sf)),
        ((-B/2*sf, H*sf), (B/2*sf,  H*sf)),
    ]
    for s, e in segs:
        msp.add_line(s, e, dxfattribs={'layer': '轮廓线'})

    # 顶板填充标记（两条斜线表示实体顶板）
    for dx in [-B/4*sf, B/4*sf]:
        msp.add_line((dx, H*sf), (dx + th*0.5, H*sf + th*0.8),
                     dxfattribs={'layer': '轮廓线'})

    # 2&3. 水面线 + 居中标注（重叠时上下错开）
    msp.add_line((-B/2*sf, h_d*sf), (B/2*sf, h_d*sf), dxfattribs={'layer': '设计水位'})
    _olap = h_inc > 0 and (h_inc - h_d) * sf < th * 2.0
    _yd = h_d*sf - th * 1.5 if _olap else h_d*sf + th * 0.5
    msp.add_text(f'▽ 设计水位 h={h_d:.3f}m', dxfattribs={
        'layer': '设计水位', 'height': th, 'style': 'FANGSONG',
        'insert': (0, _yd), 'align_point': (0, _yd), 'halign': 1})
    if h_inc > 0:
        msp.add_line((-B/2*sf, h_inc*sf), (B/2*sf, h_inc*sf),
                     dxfattribs={'layer': '加大水位', 'linetype': 'DASHED'})
        _yi = h_inc*sf + th * 0.5
        msp.add_text(f'▽ 加大水位 h={h_inc:.3f}m', dxfattribs={
            'layer': '加大水位', 'height': th, 'style': 'FANGSONG',
            'insert': (0, _yi), 'align_point': (0, _yi), 'halign': 1})

    # 4. 标注
    _add_dim_h(msp, -B/2*sf, B/2*sf, -(gap*1.1), 0, f'B={B:.3f} m', th, ar, '尺寸标注')
    _add_dim_v(msp, 0, h_d*sf, -(B/2*sf+gap*1.4), -B/2*sf, f'h={h_d:.3f} m', th, ar, '尺寸标注')
    _add_dim_v(msp, 0, H*sf,   B/2*sf+gap*1.4, B/2*sf, f'H={H:.3f} m', th, ar, '尺寸标注')
    # 净空高度标注（右侧，h_d 到 H）
    if fb_d > 0 and h_d > 0:
        _add_dim_v(msp, h_d*sf, H*sf, B/2*sf+gap*2.8, B/2*sf,
                   f'Fb={fb_d:.3f} m', th, ar, '尺寸标注')

    # 5. 参数文字
    inc_s = f'{inc:.1f}%' if isinstance(inc, (int,float)) else str(inc)
    lines = [
        '【暗涵-矩形】',
        f'比例: 1:{scale_denom}',
        '★ 经济最优断面' if is_opt else None,
        '',
        '[输入参数]',
        f'Q={Q:.3f} m³/s',
        f'n={n}',
        f'i=1/{int(si)}',
        '',
        '[断面尺寸]',
        f'B={B:.3f} m',
        f'H={H:.3f} m',
        f'β=B/h={BH:.3f}',
        '',
        '[设计流量]',
        f'h={h_d:.3f} m',
        f'A={A_d:.3f} m²',
        f'V={V_d:.3f} m/s',
        f'Fb={fb_d:.3f} m',
        '',
        '[加大流量]',
        f'比例={inc_s}',
        f'Q增={Q_inc:.3f} m³/s',
        f'h增={h_inc:.3f} m',
        f'V增={V_inc:.3f} m/s',
        f'Fb增={fb_inc:.3f} m',
    ]
    lines = [l for l in lines if l is not None]
    _add_text_block(msp, B/2*sf+gap*3.5, H*sf+th, lines, th, '参数文字')


def _scale_point(point, sf):
    return (point[0] * sf, point[1] * sf)


def _draw_arch_culvert(msp, result, p, sf=1.0, scale_denom=100):
    Q = p.get('Q', 0.0); n = p.get('n', 0.014); si = p.get('slope_inv', 3000.0)
    B = result.get('B', 0.0); H = result.get('H_total', 0.0)
    theta_deg = result.get('theta_deg', p.get('theta_deg', 180.0))
    h_d = result.get('h_design', 0.0); V_d = result.get('V_design', 0.0)
    A_d = result.get('A_design', 0.0); fb_d = result.get('freeboard_hgt_design', max(0.0, H - h_d))
    Q_inc = result.get('Q_increased', 0.0); h_inc = result.get('h_increased', 0.0)
    V_inc = result.get('V_increased', 0.0); fb_inc = result.get('freeboard_hgt_inc', max(0.0, H - h_inc))
    inc = result.get('increase_percent', 0.0)

    geom = build_arch_geometry(B, H, math.radians(theta_deg))
    char = max(B, H, 1.0) * sf
    th = 3.5
    ar = th * 0.85
    gap = char * 0.18

    outline_points = [_scale_point(point, sf) for point in build_arch_outline_polyline(geom)]
    msp.add_lwpolyline(outline_points, dxfattribs={'layer': '轮廓线'})
    msp.add_arc(
        _scale_point(geom['center'], sf),
        geom['R_arch'] * sf,
        geom['start_deg'],
        geom['end_deg'],
        dxfattribs={'layer': '轮廓线'},
    )

    overlap = h_d > 0 and h_inc > 0 and (h_inc - h_d) * sf < th * 2.0
    for h_w, layer, linetype, label in [
        (h_d, '设计水位', None, f'▽ 设计水位 h={h_d:.3f}m'),
        (h_inc, '加大水位', 'DASHED', f'▽ 加大水位 h={h_inc:.3f}m'),
    ]:
        if not h_w or h_w <= 0 or h_w >= H:
            continue
        half_width = arch_half_width(geom, h_w) * sf
        if half_width <= 1e-9:
            continue
        attribs = {'layer': layer}
        if linetype:
            attribs['linetype'] = linetype
        msp.add_line((-half_width, h_w * sf), (half_width, h_w * sf), dxfattribs=attribs)
        label_y = h_w * sf + th * 0.5 if linetype else (h_w * sf - th * 1.5 if overlap else h_w * sf + th * 0.5)
        msp.add_text(
            label,
            dxfattribs={
                'layer': layer,
                'height': th,
                'style': 'FANGSONG',
                'insert': (0, label_y),
                'align_point': (0, label_y),
                'halign': 1,
            },
        )

    _add_dim_h(msp, -B/2*sf, B/2*sf, -(gap*1.1), 0, f'B={B:.3f} m', th, ar, '尺寸标注')
    _add_dim_v(msp, 0, h_d*sf, -(B/2*sf+gap*1.4), -B/2*sf, f'h={h_d:.3f} m', th, ar, '尺寸标注')
    _add_dim_v(msp, 0, H*sf, B/2*sf+gap*1.4, B/2*sf, f'H={H:.3f} m', th, ar, '尺寸标注')
    if fb_d > 0 and h_d > 0:
        _add_dim_v(msp, h_d*sf, H*sf, B/2*sf+gap*2.8, B/2*sf, f'Fb={fb_d:.3f} m', th, ar, '尺寸标注')
    msp.add_text(
        f'θ={theta_deg:.0f}°',
        dxfattribs={'layer': '尺寸标注', 'height': th, 'style': 'FANGSONG', 'insert': (th * 0.5, H * sf)},
    )

    inc_s = f'{inc:.1f}%' if isinstance(inc, (int, float)) else str(inc)
    lines = [
        '【暗涵-圆拱直墙型】',
        f'比例: 1:{scale_denom}',
        '',
        '[输入参数]',
        f'Q={Q:.3f} m³/s',
        f'n={n}',
        f'i=1/{int(si)}',
        '',
        '[断面]',
        f'B={B:.3f} m',
        f'H={H:.3f} m',
        f'θ={theta_deg:.0f}°',
        '',
        '[设计流量]',
        f'h={h_d:.3f} m',
        f'A={A_d:.3f} m²',
        f'V={V_d:.3f} m/s',
        f'Fb={fb_d:.3f} m',
        '',
        '[加大流量]',
        f'比例={inc_s}',
        f'Q增={Q_inc:.3f}',
        f'h增={h_inc:.3f} m',
        f'V增={V_inc:.3f} m/s',
        f'Fb增={fb_inc:.3f} m',
    ]
    _add_text_block(msp, B/2*sf+gap*3.5, H*sf+th, lines, th, '参数文字')
