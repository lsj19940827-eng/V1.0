# -*- coding: utf-8 -*-
"""矩形暗涵断面 DXF 导出（封闭矩形）"""
import math
from 渠系断面设计.open_channel.dxf_export import (
    _add_layer, _add_dim_h, _add_dim_v, _add_text_block
)


def export_culvert_dxf(filepath, result, input_params, scale_denom=100):
    try:
        import ezdxf
    except ImportError:
        raise ImportError("需要安装 ezdxf 库: pip install ezdxf")

    sf = 1000.0 / scale_denom
    doc = ezdxf.new('R2010')
    doc.header['$INSUNITS'] = 4
    doc.header['$MEASUREMENT'] = 1
    doc.header['$LTSCALE'] = sf * 0.5
    _add_layer(doc, 'OUTLINE',         color=7, lw=50)
    _add_layer(doc, 'WATER_DESIGN',    color=5, lw=25)
    _add_layer(doc, 'WATER_INCREASED', color=4, lw=25)
    _add_layer(doc, 'DIMENSION',       color=2, lw=18)
    _add_layer(doc, 'TEXT_PARAMS',     color=3, lw=18)
    if 'DASHED' not in doc.linetypes:
        doc.linetypes.add('DASHED', pattern='A,.5,-.25')

    msp = doc.modelspace()
    _draw_rect_culvert(msp, result, input_params, sf, scale_denom)
    doc.saveas(filepath)


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

    char = max(B, H, 1.0)*sf; th = round(char*0.055, 3); ar = th*0.85; gap = char*0.18

    # 1. 封闭矩形轮廓（暗涵有顶板，实线）
    segs = [
        ((-B/2*sf, 0),    (B/2*sf, 0)),
        ((-B/2*sf, 0),    (-B/2*sf, H*sf)),
        ((B/2*sf,  0),    (B/2*sf,  H*sf)),
        ((-B/2*sf, H*sf), (B/2*sf,  H*sf)),
    ]
    for s, e in segs:
        msp.add_line(s, e, dxfattribs={'layer': 'OUTLINE'})

    # 顶板填充标记（两条斜线表示实体顶板）
    for dx in [-B/4*sf, B/4*sf]:
        msp.add_line((dx, H*sf), (dx + th*0.5, H*sf + th*0.8),
                     dxfattribs={'layer': 'OUTLINE'})

    # 2. 设计水面线
    msp.add_line((-B/2*sf, h_d*sf), (B/2*sf, h_d*sf), dxfattribs={'layer': 'WATER_DESIGN'})
    msp.add_text(f'▽ 设计水位 h={h_d:.3f}m', dxfattribs={
        'layer': 'WATER_DESIGN', 'height': th*0.85,
        'insert': (B/2*sf + th*0.3, h_d*sf)})

    # 3. 加大水面线（虚线）
    if h_inc > 0:
        msp.add_line((-B/2*sf, h_inc*sf), (B/2*sf, h_inc*sf),
                     dxfattribs={'layer': 'WATER_INCREASED', 'linetype': 'DASHED'})
        msp.add_text(f'▽ 加大水位 h={h_inc:.3f}m', dxfattribs={
            'layer': 'WATER_INCREASED', 'height': th*0.85,
            'insert': (B/2*sf + th*0.3, h_inc*sf + th*0.5)})

    # 4. 标注
    _add_dim_h(msp, -B/2*sf, B/2*sf, -(gap*1.1), 0, f'B={B:.3f} m', th, ar, 'DIMENSION')
    _add_dim_v(msp, 0, h_d*sf, -(B/2*sf+gap*1.4), -B/2*sf, f'h={h_d:.3f} m', th, ar, 'DIMENSION')
    _add_dim_v(msp, 0, H*sf,   B/2*sf+gap*1.4, B/2*sf, f'H={H:.3f} m', th, ar, 'DIMENSION')
    # 净空高度标注（右侧，h_d 到 H）
    if fb_d > 0 and h_d > 0:
        _add_dim_v(msp, h_d*sf, H*sf, B/2*sf+gap*2.8, B/2*sf,
                   f'Fb={fb_d:.3f} m', th, ar, 'DIMENSION')

    # 5. 参数文字
    inc_s = f'{inc:.1f}%' if isinstance(inc, (int,float)) else str(inc)
    lines = [
        '【矩形暗渠水力计算】',
        f'比例: 1:{scale_denom}',
        '★ 水力最佳断面' if is_opt else None,
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
    _add_text_block(msp, B/2*sf+gap*3.5, H*sf+th, lines, th, 'TEXT_PARAMS')
