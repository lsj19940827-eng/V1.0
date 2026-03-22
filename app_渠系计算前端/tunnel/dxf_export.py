# -*- coding: utf-8 -*-
"""隧洞断面 DXF 导出（圆形 / 圆拱直墙型 / 马蹄形）"""
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
    build_standard_horseshoe_geometry,
    standard_horseshoe_half_width,
)


def export_tunnel_dxf(filepath, result, input_params, scale_denom=100):
    try:
        import ezdxf
    except ImportError:
        raise ImportError("需要安装 ezdxf 库: pip install ezdxf")
    doc = ezdxf.new('R2010')
    setup_section_dxf_document(doc, scale_denom=scale_denom)
    draw_tunnel_dxf_on_msp(
        doc.modelspace(),
        result,
        input_params,
        scale_denom=scale_denom,
    )
    doc.saveas(filepath)


def draw_tunnel_dxf_on_msp(
    msp,
    result,
    input_params,
    scale_denom=100,
    layer_prefix="",
    title="",
):
    tracked_msp = ensure_tracked_msp(msp, layer_prefix=layer_prefix)
    stype = input_params.get('section_type', '圆形')
    sf = 1000.0 / scale_denom
    if stype == '圆形':
        _draw_circ(tracked_msp, result, input_params, sf, scale_denom)
    elif stype == '圆拱直墙型':
        _draw_arch(tracked_msp, result, input_params, sf, scale_denom)
    else:
        sec_t = input_params.get('sec_type_int', 1 if 'Ⅰ' in stype else 2)
        _draw_shoe(tracked_msp, result, input_params, sec_t, sf, scale_denom)
    if title:
        add_case_title(tracked_msp, title)
    return tracked_msp.size()


def _scale_point(point, sf):
    return (point[0] * sf, point[1] * sf)



def _draw_circ(msp, result, p, sf=1.0, scale_denom=100):
    Q = p.get('Q', 0.0); n = p.get('n', 0.014); si = p.get('slope_inv', 3000.0)
    D = result.get('D', 0.0); R = D / 2
    h_d  = result.get('h_design', 0.0); V_d  = result.get('V_design', 0.0)
    A_d  = result.get('A_design', 0.0)
    fb_d = result.get('freeboard_hgt_design', D - h_d)
    Q_inc = result.get('Q_increased', 0.0); h_inc = result.get('h_increased', 0.0)
    V_inc = result.get('V_increased', 0.0); fb_inc = result.get('freeboard_hgt_inc', D - h_inc)
    inc = result.get('increase_percent', 0.0)

    char = max(D, 1.0)*sf; th = 3.5; ar = th*0.85; gap = char*0.20

    msp.add_circle((0, R*sf), R*sf, dxfattribs={'layer': '轮廓线'})
    msp.add_line((-R*1.5*sf, 0), (R*1.5*sf, 0), dxfattribs={'layer': '轮廓线', 'linetype': 'DASHED'})

    _olap_c = h_d > 0 and h_inc > 0 and 0 < h_inc < D and (h_inc - h_d) * sf < th * 2.0
    for h_w, layer, lt, lbl in [
        (h_d,  '设计水位',    None,     f'▽ 设计水位 h={h_d:.3f}m'),
        (h_inc,'加大水位', 'DASHED', f'▽ 加大水位 h={h_inc:.3f}m'),
    ]:
        if h_w and 0 < h_w < D:
            hw = math.sqrt(max(0, R**2 - (R - h_w)**2)) * sf
            att = {'layer': layer}
            if lt: att['linetype'] = lt
            msp.add_line((-hw, h_w*sf), (hw, h_w*sf), dxfattribs=att)
            _ly = h_w*sf + th*0.5 if lt else (h_w*sf - th*1.5 if _olap_c else h_w*sf + th*0.5)
            msp.add_text(lbl, dxfattribs={'layer': layer, 'height': th, 'style': 'FANGSONG',
                'insert': (0, _ly), 'align_point': (0, _ly), 'halign': 1})

    _add_dim_h(msp, -R*sf, R*sf, -(gap*1.1), 0, f'D={D:.2f} m', th, ar, '尺寸标注')
    if h_d > 0:
        _add_dim_v(msp, 0, h_d*sf, -(R*sf+gap*1.4), -R*sf, f'h={h_d:.3f} m', th, ar, '尺寸标注')
    if fb_d > 0 and h_d > 0:
        _add_dim_v(msp, h_d*sf, D*sf, R*sf+gap*1.4, R*sf, f'Fb={fb_d:.3f} m', th, ar, '尺寸标注')
    msp.add_line((0, R*sf), (R*sf*0.707, R*sf+R*sf*0.707), dxfattribs={'layer': '尺寸标注'})
    msp.add_text(f'R={R:.3f} m', dxfattribs={'layer': '尺寸标注', 'height': th, 'style': 'FANGSONG',
        'insert': (R*sf*0.72, R*sf+R*sf*0.72)})

    inc_s = f'{inc:.1f}%' if isinstance(inc, (int,float)) else str(inc)
    lines = ['【隧洞 - 圆形】', f'比例: 1:{scale_denom}', '',
             '[输入参数]', f'Q={Q:.3f} m³/s', f'n={n}', f'i=1/{int(si)}','',
             '[断面]', f'D={D:.2f} m','',
             '[设计流量]', f'h={h_d:.3f} m', f'A={A_d:.3f} m²',
             f'V={V_d:.3f} m/s', f'Fb={fb_d:.3f} m','',
             '[加大流量]', f'比例={inc_s}', f'Q增={Q_inc:.3f}',
             f'h增={h_inc:.3f} m', f'V增={V_inc:.3f} m/s', f'Fb增={fb_inc:.3f} m']
    _add_text_block(msp, R*sf+gap*3.5, D*sf+th, lines, th, '参数文字')


def _draw_arch(msp, result, p, sf=1.0, scale_denom=100):
    Q = p.get('Q', 0.0); n = p.get('n', 0.014); si = p.get('slope_inv', 3000.0)
    B = result.get('B', 0.0); H = result.get('H_total', 0.0)
    theta_deg = result.get('theta_deg', 180.0)
    h_d  = result.get('h_design', 0.0); V_d  = result.get('V_design', 0.0)
    A_d  = result.get('A_design', 0.0); fb_d = result.get('freeboard_hgt_design', H-h_d)
    Q_inc = result.get('Q_increased', 0.0); h_inc = result.get('h_increased', 0.0)
    V_inc = result.get('V_increased', 0.0); fb_inc = result.get('freeboard_hgt_inc', H-h_inc)
    inc = result.get('increase_percent', 0.0)

    tr = math.radians(theta_deg)
    geom = build_arch_geometry(B, H, tr)
    Hs = geom['H_straight']

    char = max(B, H, 1.0)*sf; th = 3.5; ar = th*0.85; gap = char*0.18

    # 非圆弧边界改为多段线，拱顶使用原生 ARC
    outline_points = [_scale_point(point, sf) for point in build_arch_outline_polyline(geom)]
    msp.add_lwpolyline(outline_points, dxfattribs={'layer': '轮廓线'})
    msp.add_arc(
        _scale_point(geom['center'], sf),
        geom['R_arch'] * sf,
        geom['start_deg'],
        geom['end_deg'],
        dxfattribs={'layer': '轮廓线'},
    )

    # 水面线 + 居中标注（重叠时上下错开）
    _olap_a = h_d > 0 and h_inc > 0 and (h_inc - h_d) * sf < th * 2.0
    for h_w, layer, lt, lbl in [
        (h_d,  '设计水位',    None,     f'▽ 设计水位 h={h_d:.3f}m'),
        (h_inc,'加大水位', 'DASHED', f'▽ 加大水位 h={h_inc:.3f}m'),
    ]:
        if h_w and 0 < h_w < H:
            hw = arch_half_width(geom, h_w) * sf
            if hw <= 1e-9:
                continue
            att = {'layer': layer}
            if lt: att['linetype'] = lt
            msp.add_line((-hw, h_w*sf), (hw, h_w*sf), dxfattribs=att)
            _ly = h_w*sf + th*0.5 if lt else (h_w*sf - th*1.5 if _olap_a else h_w*sf + th*0.5)
            msp.add_text(lbl, dxfattribs={'layer': layer, 'height': th, 'style': 'FANGSONG',
                'insert': (0, _ly), 'align_point': (0, _ly), 'halign': 1})

    _add_dim_h(msp, -B/2*sf, B/2*sf, -(gap*1.1), 0, f'B={B:.3f} m', th, ar, '尺寸标注')
    _add_dim_v(msp, 0, h_d*sf, -(B/2*sf+gap*1.4), -B/2*sf, f'h={h_d:.3f} m', th, ar, '尺寸标注')
    _add_dim_v(msp, 0, H*sf,   B/2*sf+gap*1.4, B/2*sf, f'H={H:.3f} m', th, ar, '尺寸标注')
    if Hs > 0:
        msp.add_text(f'θ={theta_deg:.0f}°', dxfattribs={'layer': '尺寸标注',
            'height': th, 'style': 'FANGSONG', 'insert': (th*0.5, H*sf)})

    inc_s = f'{inc:.1f}%' if isinstance(inc, (int,float)) else str(inc)
    lines = ['【隧洞 - 圆拱直墙型】', f'比例: 1:{scale_denom}', '',
             '[输入参数]', f'Q={Q:.3f} m³/s', f'n={n}', f'i=1/{int(si)}','',
             '[断面]', f'B={B:.3f} m', f'H={H:.3f} m', f'θ={theta_deg:.0f}°','',
             '[设计流量]', f'h={h_d:.3f} m', f'A={A_d:.3f} m²',
             f'V={V_d:.3f} m/s', f'Fb={fb_d:.3f} m','',
             '[加大流量]', f'比例={inc_s}', f'Q增={Q_inc:.3f}',
             f'h增={h_inc:.3f} m', f'V增={V_inc:.3f} m/s', f'Fb增={fb_inc:.3f} m']
    _add_text_block(msp, B/2*sf+gap*3.5, H*sf+th, lines, th, '参数文字')


def _draw_shoe(msp, result, p, sec_type, sf=1.0, scale_denom=100):
    Q = p.get('Q', 0.0); n = p.get('n', 0.014); si = p.get('slope_inv', 3000.0)
    r = result.get('r', 0.0)
    h_d  = result.get('h_design', 0.0); V_d  = result.get('V_design', 0.0)
    A_d  = result.get('A_design', 0.0); fb_d = result.get('freeboard_hgt_design', 2*r-h_d)
    Q_inc = result.get('Q_increased', 0.0); h_inc = result.get('h_increased', 0.0)
    V_inc = result.get('V_increased', 0.0); fb_inc = result.get('freeboard_hgt_inc', 2*r-h_inc)
    inc = result.get('increase_percent', 0.0)

    geom = build_standard_horseshoe_geometry(sec_type, r)
    name = geom['type_name']

    char = max(2*r, 1.0)*sf; th = 3.5; ar = th*0.85; gap = char*0.20

    for arc in geom['arcs']:
        msp.add_arc(
            _scale_point(arc['center'], sf),
            arc['radius'] * sf,
            arc['start_deg'],
            arc['end_deg'],
            dxfattribs={'layer': '轮廓线'},
        )

    _olap_s = h_d > 0 and h_inc > 0 and 0 < h_inc < 2*r and (h_inc - h_d) * sf < th * 2.0
    for h_w, layer, lt, lbl in [
        (h_d,  '设计水位',    None,     f'▽ 设计水位 h={h_d:.3f}m'),
        (h_inc,'加大水位', 'DASHED', f'▽ 加大水位 h={h_inc:.3f}m'),
    ]:
        if h_w and 0 < h_w < 2*r:
            hw = standard_horseshoe_half_width(geom, h_w) * sf
            att = {'layer': layer}
            if lt: att['linetype'] = lt
            msp.add_line((-hw, h_w*sf), (hw, h_w*sf), dxfattribs=att)
            _ly = h_w*sf + th*0.5 if lt else (h_w*sf - th*1.5 if _olap_s else h_w*sf + th*0.5)
            msp.add_text(lbl, dxfattribs={'layer': layer, 'height': th, 'style': 'FANGSONG',
                'insert': (0, _ly), 'align_point': (0, _ly), 'halign': 1})

    _add_dim_h(msp, -r*sf, r*sf, -(gap*1.1), 0, f'2r={2*r:.3f} m', th, ar, '尺寸标注')
    _add_dim_v(msp, 0, h_d*sf,  -(r*sf+gap*1.4), -r*sf, f'h={h_d:.3f} m', th, ar, '尺寸标注')
    _add_dim_v(msp, 0, 2*r*sf,  r*sf+gap*1.4, r*sf, f'H=2r={2*r:.3f} m', th, ar, '尺寸标注')
    msp.add_line((0, r*sf), (r*sf*0.7, r*sf), dxfattribs={'layer': '尺寸标注'})
    msp.add_text(f'r={r:.3f} m', dxfattribs={'layer': '尺寸标注',
        'height': th, 'style': 'FANGSONG', 'insert': (r*sf*0.72, r*sf+th*0.3)})

    inc_s = f'{inc:.1f}%' if isinstance(inc, (int,float)) else str(inc)
    lines = [f'【隧洞 - 马蹄形{name}】', f'比例: 1:{scale_denom}', '',
             '[输入参数]', f'Q={Q:.3f} m\u00b3/s', f'n={n}', f'i=1/{int(si)}','',
             '[断面]', f'r={r:.3f} m', f'H=2r={2*r:.3f} m','',
             '[设计流量]', f'h={h_d:.3f} m', f'A={A_d:.3f} m\u00b2',
             f'V={V_d:.3f} m/s', f'Fb={fb_d:.3f} m','',
             '[加大流量]', f'比例={inc_s}', f'Q\u589e={Q_inc:.3f}',
             f'h\u589e={h_inc:.3f} m', f'V\u589e={V_inc:.3f} m/s', f'Fb\u589e={fb_inc:.3f} m']
    _add_text_block(msp, r*sf+gap*3.5, 2*r*sf+th, lines, th, '参数文字')
