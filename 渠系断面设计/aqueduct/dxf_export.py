# -*- coding: utf-8 -*-
"""渡槽断面 DXF 导出（U形 / 矩形）"""
import math
from 渠系断面设计.open_channel.dxf_export import (
    _setup_font_style, _add_layer, _add_dim_h, _add_dim_v, _add_text_block
)


def export_aqueduct_dxf(filepath, result, input_params, scale_denom=100):
    try:
        import ezdxf
    except ImportError:
        raise ImportError("需要安装 ezdxf 库: pip install ezdxf")

    stype = result.get('section_type', input_params.get('section_type', 'U形'))
    sf = 1000.0 / scale_denom
    doc = ezdxf.new('R2010')
    doc.header['$INSUNITS'] = 4
    doc.header['$MEASUREMENT'] = 1
    doc.header['$LTSCALE'] = sf * 0.5
    _add_layer(doc, '轮廓线',         color=7, lw=50)
    _add_layer(doc, '设计水位',    color=5, lw=25)
    _add_layer(doc, '加大水位', color=4, lw=25)
    _add_layer(doc, '尺寸标注',       color=2, lw=18)
    _add_layer(doc, '参数文字',     color=3, lw=18)
    if 'DASHED' not in doc.linetypes:
        doc.linetypes.add('DASHED', pattern='A,.5,-.25')
    _setup_font_style(doc)
    msp = doc.modelspace()
    if stype == 'U形':
        _draw_u(msp, result, input_params, sf, scale_denom)
    else:
        _draw_rect(msp, result, input_params, sf, scale_denom)
    doc.saveas(filepath)


def _draw_u(msp, result, p, sf=1.0, scale_denom=100):
    Q = p.get('Q', 0.0); n = p.get('n', 0.014); si = p.get('slope_inv', 3000.0)
    R = result.get('R', 0.0); f = result.get('f', 0.0)
    B = result.get('B', 2*R); H = result.get('H_total', R+f)
    h_d = result.get('h_design', 0.0); V_d = result.get('V_design', 0.0)
    A_d = result.get('A_design', 0.0)
    Q_inc = result.get('Q_increased', 0.0); h_inc = result.get('h_increased', 0.0)
    V_inc = result.get('V_increased', 0.0); Fb = result.get('Fb', 0.0)
    inc = result.get('increase_percent', 0.0)

    char = max(B, H, 1.0)*sf; th = 3.5; ar = th*0.85; gap = char*0.18

    # 轮廓：下半圆 + 两侧直墙 + 顶部虚线
    N = 40
    for i in range(N):
        a1 = math.pi + i*math.pi/N; a2 = math.pi + (i+1)*math.pi/N
        msp.add_line((R*math.cos(a1)*sf, (R+R*math.sin(a1))*sf),
                     (R*math.cos(a2)*sf, (R+R*math.sin(a2))*sf), dxfattribs={'layer': '轮廓线'})
    msp.add_line((-R*sf, R*sf), (-R*sf, H*sf), dxfattribs={'layer': '轮廓线'})
    msp.add_line((R*sf,  R*sf), (R*sf,  H*sf), dxfattribs={'layer': '轮廓线'})
    msp.add_line((-R*sf, H*sf), (R*sf, H*sf),  dxfattribs={'layer': '轮廓线', 'linetype': 'DASHED'})

    # 水面线 + 居中标注（重叠时上下错开）
    _olap_u = h_d > 0 and h_inc > 0 and (h_inc - h_d) * sf < th * 2.0
    for h_w, layer, lt, lbl in [
        (h_d,  '设计水位',    None,     f'▽ 设计水位 h={h_d:.3f}m'),
        (h_inc,'加大水位', 'DASHED', f'▽ 加大水位 h={h_inc:.3f}m'),
    ]:
        if h_w and h_w > 0:
            hw = (math.sqrt(max(0, R**2 - (R-h_w)**2)) if h_w <= R else R) * sf
            att = {'layer': layer}
            if lt: att['linetype'] = lt
            msp.add_line((-hw, h_w*sf), (hw, h_w*sf), dxfattribs=att)
            _ly = h_w*sf + th*0.5 if lt else (h_w*sf - th*1.5 if _olap_u else h_w*sf + th*0.5)
            msp.add_text(lbl, dxfattribs={'layer': layer, 'height': th, 'style': 'FANGSONG',
                'insert': (0, _ly), 'align_point': (0, _ly), 'halign': 1})

    # 标注
    _add_dim_h(msp, -R*sf, R*sf, -(gap*1.1), 0, f'B={B:.3f} m', th, ar, '尺寸标注')
    _add_dim_v(msp, 0, R*sf, -(R*sf+gap*1.4), -R*sf, f'R={R:.3f} m', th, ar, '尺寸标注')
    if f > 0:
        _add_dim_v(msp, R*sf, H*sf, R*sf+gap*1.4, R*sf, f'f={f:.3f} m', th, ar, '尺寸标注')
    _add_dim_v(msp, 0, H*sf, R*sf+gap*2.8, R*sf, f'H={H:.3f} m', th, ar, '尺寸标注')

    inc_s = f'{inc:.1f}%' if isinstance(inc, (int,float)) else str(inc)
    lines = ['【渡槽 - U形】', f'比例: 1:{scale_denom}', '',
             '[输入参数]', f'Q={Q:.3f} m\u00b3/s', f'n={n}', f'i=1/{int(si)}','',
             '[断面尺寸]', f'R={R:.3f} m', f'f={f:.3f} m', f'B={B:.3f} m', f'H={H:.3f} m','',
             '[设计流量]', f'h={h_d:.3f} m', f'A={A_d:.3f} m\u00b2', f'V={V_d:.3f} m/s','',
             '[加大流量]', f'比例={inc_s}', f'Q\u589e={Q_inc:.3f}', f'h\u589e={h_inc:.3f} m',
             f'V\u589e={V_inc:.3f} m/s', f'Fb={Fb:.3f} m']
    _add_text_block(msp, R*sf+gap*4, H*sf+th, lines, th, '参数文字')


def _draw_rect(msp, result, p, sf=1.0, scale_denom=100):
    Q = p.get('Q', 0.0); n = p.get('n', 0.014); si = p.get('slope_inv', 3000.0)
    B = result.get('B', 0.0); H = result.get('H_total', 0.0)
    h_d = result.get('h_design', 0.0); V_d = result.get('V_design', 0.0)
    A_d = result.get('A_design', 0.0)
    Q_inc = result.get('Q_increased', 0.0); h_inc = result.get('h_increased', 0.0)
    V_inc = result.get('V_increased', 0.0); Fb = result.get('Fb', 0.0)
    inc = result.get('increase_percent', 0.0)
    has_ch = result.get('has_chamfer', False)
    ch_ang = result.get('chamfer_angle', 0); ch_len = result.get('chamfer_length', 0)

    char = max(B, H, 1.0)*sf; th = 3.5; ar = th*0.85; gap = char*0.18

    if has_ch and ch_len > 0 and ch_ang > 0:
        dy = ch_len*math.sin(math.radians(ch_ang))*sf; dx = ch_len*math.cos(math.radians(ch_ang))*sf
        segs = [((-B/2*sf+dx, 0), (B/2*sf-dx, 0)), ((B/2*sf-dx, 0), (B/2*sf, dy)),
                ((B/2*sf, dy), (B/2*sf, H*sf)), ((-B/2*sf, dy), (-B/2*sf, H*sf)),
                ((-B/2*sf+dx, 0), (-B/2*sf, dy))]
        for s, e in segs:
            msp.add_line(s, e, dxfattribs={'layer': '轮廓线'})
    else:
        msp.add_line((-B/2*sf, 0), (B/2*sf, 0),    dxfattribs={'layer': '轮廓线'})
        msp.add_line((-B/2*sf, 0), (-B/2*sf, H*sf), dxfattribs={'layer': '轮廓线'})
        msp.add_line((B/2*sf, 0),  (B/2*sf, H*sf),  dxfattribs={'layer': '轮廓线'})
    msp.add_line((-B/2*sf, H*sf), (B/2*sf, H*sf), dxfattribs={'layer': '轮廓线', 'linetype': 'DASHED'})

    _olap_r = h_d > 0 and h_inc > 0 and (h_inc - h_d) * sf < th * 2.0
    for h_w, layer, lt, lbl in [
        (h_d,  '设计水位',    None,     f'▽ 设计水位 h={h_d:.3f}m'),
        (h_inc,'加大水位', 'DASHED', f'▽ 加大水位 h={h_inc:.3f}m'),
    ]:
        if h_w and h_w > 0:
            att = {'layer': layer}
            if lt: att['linetype'] = lt
            msp.add_line((-B/2*sf, h_w*sf), (B/2*sf, h_w*sf), dxfattribs=att)
            _ly = h_w*sf + th*0.5 if lt else (h_w*sf - th*1.5 if _olap_r else h_w*sf + th*0.5)
            msp.add_text(lbl, dxfattribs={'layer': layer, 'height': th, 'style': 'FANGSONG',
                'insert': (0, _ly), 'align_point': (0, _ly), 'halign': 1})

    _add_dim_h(msp, -B/2*sf, B/2*sf, -(gap*1.1), 0, f'B={B:.3f} m', th, ar, '尺寸标注')
    _add_dim_v(msp, 0, h_d*sf, -(B/2*sf+gap*1.4), -B/2*sf, f'h={h_d:.3f} m', th, ar, '尺寸标注')
    _add_dim_v(msp, 0, H*sf,   B/2*sf+gap*1.4, B/2*sf, f'H={H:.3f} m', th, ar, '尺寸标注')

    inc_s = f'{inc:.1f}%' if isinstance(inc, (int,float)) else str(inc)
    lines = ['【渡槽 - 矩形】', f'比例: 1:{scale_denom}', '',
             '[输入参数]', f'Q={Q:.3f} m\u00b3/s', f'n={n}', f'i=1/{int(si)}','',
             '[断面尺寸]', f'B={B:.3f} m', f'H={H:.3f} m']
    if has_ch:
        lines += [f'倒角={ch_ang}\u00b0', f'底边长={ch_len} m']
    lines += ['', '[设计流量]', f'h={h_d:.3f} m', f'A={A_d:.3f} m\u00b2', f'V={V_d:.3f} m/s',
              '', '[加大流量]', f'比例={inc_s}', f'Q\u589e={Q_inc:.3f}',
              f'h\u589e={h_inc:.3f} m', f'V\u589e={V_inc:.3f} m/s', f'Fb={Fb:.3f} m']
    _add_text_block(msp, B/2*sf+gap*3.5, H*sf+th, lines, th, '参数文字')
