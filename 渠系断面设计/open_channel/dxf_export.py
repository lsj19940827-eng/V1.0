# -*- coding: utf-8 -*-
"""
明渠断面 DXF 导出模块

内容：断面轮廓线 + 水面线(设计/加大) + 尺寸标注 + 参数文字块
支持：梯形 / 矩形 / 圆形断面
"""

import math


def export_open_channel_dxf(filepath, result, input_params, scale_denom=100):
    """导出明渠断面 DXF 文件（完整版：轮廓+水面线+标注+参数文字）"""
    try:
        import ezdxf
    except ImportError:
        raise ImportError("需要安装 ezdxf 库: pip install ezdxf")

    stype = input_params.get('section_type', '梯形')

    sf = 1000.0 / scale_denom

    doc = ezdxf.new('R2010')
    doc.header['$INSUNITS'] = 4    # 4 = mm (paper units)
    doc.header['$MEASUREMENT'] = 1  # 1 = metric
    doc.header['$LTSCALE'] = sf * 0.5

    # 图层定义  ACI: 1=红 2=黄 3=绿 4=青 5=蓝 7=白/黑
    _add_layer(doc, 'OUTLINE',          color=7,  lw=50)
    _add_layer(doc, 'WATER_DESIGN',     color=5,  lw=25)
    _add_layer(doc, 'WATER_INCREASED',  color=4,  lw=25)
    _add_layer(doc, 'DIMENSION',        color=2,  lw=18)
    _add_layer(doc, 'TEXT_PARAMS',      color=3,  lw=18)

    # 虚线线型
    if 'DASHED' not in doc.linetypes:
        doc.linetypes.add('DASHED', pattern='A,.5,-.25')

    msp = doc.modelspace()

    if stype == '圆形':
        _draw_circular(msp, result, input_params, sf, scale_denom)
    else:
        _draw_trapezoid(msp, result, input_params, sf, scale_denom)

    doc.saveas(filepath)


# ============================================================
# 内部工具
# ============================================================

def _add_layer(doc, name, color, lw):
    layer = doc.layers.add(name)
    layer.color = color
    layer.lineweight = lw


def _add_arrow_tip(msp, tip, direction_vec, size, layer):
    """在 tip 处绘制方向为 direction_vec 的箭头尖"""
    dx, dy = direction_vec
    length = math.hypot(dx, dy)
    if length == 0:
        return
    ux, uy = dx / length, dy / length
    px, py = -uy, ux  # 垂直方向
    p1 = (tip[0] - ux * size + px * size * 0.3,
          tip[1] - uy * size + py * size * 0.3)
    p2 = (tip[0] - ux * size - px * size * 0.3,
          tip[1] - uy * size - py * size * 0.3)
    msp.add_solid([tip, p1, p2, tip], dxfattribs={'layer': layer})


def _add_dim_h(msp, x1, x2, y_line, y_orig, label, txt_h, arr, layer):
    """水平尺寸标注"""
    ext_ext = arr * 0.5
    # 延伸线
    for x, y0 in [(x1, y_orig), (x2, y_orig)]:
        sign = -1 if y_line < y_orig else 1
        msp.add_line((x, y0), (x, y_line + sign * ext_ext),
                     dxfattribs={'layer': layer})
    # 尺寸线
    msp.add_line((x1, y_line), (x2, y_line), dxfattribs={'layer': layer})
    # 箭头
    _add_arrow_tip(msp, (x1, y_line), (x1 - x2, 0), arr, layer)
    _add_arrow_tip(msp, (x2, y_line), (x2 - x1, 0), arr, layer)
    # 文字
    msp.add_text(label, dxfattribs={
        'layer': layer, 'height': txt_h,
        'insert': ((x1 + x2) / 2, y_line - txt_h * 1.4),
    })


def _add_dim_v(msp, y1, y2, x_line, x_orig, label, txt_h, arr, layer):
    """垂直尺寸标注"""
    ext_ext = arr * 0.5
    for y, x0 in [(y1, x_orig), (y2, x_orig)]:
        sign = -1 if x_line < x_orig else 1
        msp.add_line((x0, y), (x_line + sign * ext_ext, y),
                     dxfattribs={'layer': layer})
    msp.add_line((x_line, y1), (x_line, y2), dxfattribs={'layer': layer})
    _add_arrow_tip(msp, (x_line, y1), (0, y1 - y2), arr, layer)
    _add_arrow_tip(msp, (x_line, y2), (0, y2 - y1), arr, layer)
    mid_y = (y1 + y2) / 2
    msp.add_text(label, dxfattribs={
        'layer': layer, 'height': txt_h,
        'insert': (x_line - txt_h * 1.5, mid_y),
        'rotation': 90,
    })


def _add_text_block(msp, x, y_start, lines, txt_h, layer):
    """逐行输出参数文字块"""
    for line in lines:
        if not line:
            y_start -= txt_h * 0.8
            continue
        is_header = line.startswith('[') or line.startswith('【')
        h = txt_h if is_header else txt_h * 0.85
        indent = 0 if is_header else txt_h * 0.5
        msp.add_text(line, dxfattribs={
            'layer': layer, 'height': h,
            'insert': (x + indent, y_start),
        })
        y_start -= h * 1.6


# ============================================================
# 梯形 / 矩形
# ============================================================

def _draw_trapezoid(msp, result, p, sf=1.0, scale_denom=100):
    stype = p.get('section_type', '梯形')
    m     = p.get('m', 0.0)
    Q     = p.get('Q', 0.0)
    n     = p.get('n', 0.014)
    slope_inv = p.get('slope_inv', 3000.0)

    b     = result.get('b_design', 0.0)
    h     = result.get('h_design', 0.0)
    H     = result.get('h_prime', 0.0)
    h_inc = result.get('h_increased', 0.0)
    V     = result.get('V_design', 0.0)
    Q_inc = result.get('Q_increased', 0.0)
    V_inc = result.get('V_increased', 0.0)
    inc_pct = result.get('increase_percent', 0.0)
    A     = result.get('A_design', 0.0)
    R     = result.get('R_design', 0.0)
    Fb    = result.get('Fb', 0.0)
    beta  = result.get('Beta_design', 0.0)

    if H <= 0:
        H = (h_inc + 0.3) if h_inc > 0 else h * 1.35

    char  = max(b, H, 1.0) * sf
    txt_h = round(char * 0.055, 3)
    arr   = txt_h * 0.85
    gap   = char * 0.18

    top_w = b + 2 * m * H

    # ------ 1. 轮廓线 ------
    if m > 0:
        outline = [(-b/2*sf, 0), (b/2*sf, 0), ((b/2+m*H)*sf, H*sf), (-(b/2+m*H)*sf, H*sf)]
    else:
        outline = [(-b/2*sf, 0), (b/2*sf, 0), (b/2*sf, H*sf), (-b/2*sf, H*sf)]

    for i in range(len(outline)):
        msp.add_line(outline[i], outline[(i+1) % len(outline)],
                     dxfattribs={'layer': 'OUTLINE'})

    # ------ 2. 设计水面线 ------
    hw_d = b + 2 * m * h
    msp.add_line((-hw_d/2*sf, h*sf), (hw_d/2*sf, h*sf),
                 dxfattribs={'layer': 'WATER_DESIGN'})
    msp.add_text(f'▽ 设计水位  h={h:.3f}m', dxfattribs={
        'layer': 'WATER_DESIGN', 'height': txt_h * 0.85,
        'insert': (hw_d/2*sf + txt_h * 0.3, h*sf),
    })

    # ------ 3. 加大水面线（虚线）------
    if h_inc > 0:
        hw_i = b + 2 * m * h_inc
        msp.add_line((-hw_i/2*sf, h_inc*sf), (hw_i/2*sf, h_inc*sf),
                     dxfattribs={'layer': 'WATER_INCREASED', 'linetype': 'DASHED'})
        msp.add_text(f'▽ 加大水位  h={h_inc:.3f}m', dxfattribs={
            'layer': 'WATER_INCREASED', 'height': txt_h * 0.85,
            'insert': (hw_i/2*sf + txt_h * 0.3, h_inc*sf + txt_h * 0.5),
        })

    # ------ 4. 尺寸标注 ------
    _add_dim_h(msp,
               x1=-b/2*sf, x2=b/2*sf,
               y_line=-(gap * 1.1), y_orig=0,
               label=f'B={b:.3f} m',
               txt_h=txt_h, arr=arr, layer='DIMENSION')

    x_left = -(top_w/2*sf + gap * 1.4)
    _add_dim_v(msp,
               y1=0, y2=h*sf,
               x_line=x_left, x_orig=-(b/2 + m*h)*sf,
               label=f'h={h:.3f} m',
               txt_h=txt_h, arr=arr, layer='DIMENSION')

    x_right = top_w/2*sf + gap * 1.4
    _add_dim_v(msp,
               y1=0, y2=H*sf,
               x_line=x_right, x_orig=top_w/2*sf,
               label=f'H={H:.3f} m',
               txt_h=txt_h, arr=arr, layer='DIMENSION')

    if m > 0:
        mid_y = H / 2
        mid_x = b/2 + m * mid_y
        slope_angle = math.degrees(math.atan2(H, m * H))
        msp.add_text(f'1:{m:.1f}', dxfattribs={
            'layer': 'DIMENSION', 'height': txt_h * 0.9,
            'insert': (mid_x*sf + txt_h * 0.5, mid_y*sf),
            'rotation': slope_angle,
        })

    # ------ 5. 参数文字块（右侧）------
    text_x = top_w/2*sf + gap * 3.5
    inc_pct_str = (f'{inc_pct:.1f}%' if isinstance(inc_pct, (int, float))
                   else str(inc_pct))

    lines = [
        '【明渠水力计算】',
        f'断面类型: {stype}',
        '',
        '[输入参数]',
        f'Q = {Q:.3f} m\u00b3/s',
        f'n = {n}',
        f'i = 1/{int(slope_inv)}',
    ]
    if stype == '梯形':
        lines.append(f'm = {m}')
    lines += [
        '',
        '[断面尺寸]',
        f'B = {b:.3f} m',
        f'h = {h:.3f} m',
        f'\u03b2 = {beta:.3f}',
        f'H = {H:.3f} m',
        '',
        '[设计流量工况]',
        f'A = {A:.3f} m\u00b2',
        f'R = {R:.3f} m',
        f'V = {V:.3f} m/s',
    ]
    if h_inc > 0:
        lines += [
            '',
            '[加大流量工况]',
            f'加大比例 = {inc_pct_str}',
            f'Q\u589e = {Q_inc:.3f} m\u00b3/s',
            f'h\u589e = {h_inc:.3f} m',
            f'V\u589e = {V_inc:.3f} m/s',
            f'Fb = {Fb:.3f} m',
        ]

    lines.insert(1, f'比例: 1:{scale_denom}')
    _add_text_block(msp, text_x, H*sf + txt_h, lines, txt_h, 'TEXT_PARAMS')


# ============================================================
# 圆形
# ============================================================

def _draw_circular(msp, result, p, sf=1.0, scale_denom=100):
    Q     = p.get('Q', 0.0)
    n     = p.get('n', 0.014)
    slope_inv = p.get('slope_inv', 3000.0)

    D     = result.get('D_design', 0.0)
    y_d   = result.get('y_d', 0.0)
    V_d   = result.get('V_d', 0.0)
    A_d   = result.get('A_d', 0.0)
    FB_d  = result.get('FB_d', 0.0)
    PA_d  = result.get('PA_d', 0.0)

    inc_info = result.get('increase_percent', '')
    Q_inc = result.get('Q_inc', 0.0)
    y_i   = result.get('y_i', 0.0)
    V_i   = result.get('V_i', 0.0)
    FB_i  = result.get('FB_i', 0.0)
    PA_i  = result.get('PA_i', 0.0)

    R = D / 2
    char  = max(D, 1.0) * sf
    txt_h = round(char * 0.06, 3)
    arr   = txt_h * 0.85
    gap   = char * 0.20

    cx, cy = 0.0, R * sf

    # ------ 1. 轮廓圆 ------
    msp.add_circle((cx, cy), R*sf, dxfattribs={'layer': 'OUTLINE'})
    msp.add_line((-R*1.5*sf, 0), (R*1.5*sf, 0),
                 dxfattribs={'layer': 'OUTLINE', 'linetype': 'DASHED'})

    # ------ 2. 设计水面线 ------
    if 0 < y_d < D:
        half_w = math.sqrt(max(0, R**2 - (R - y_d)**2)) * sf
        msp.add_line((-half_w, y_d*sf), (half_w, y_d*sf),
                     dxfattribs={'layer': 'WATER_DESIGN'})
        msp.add_text(f'▽ 设计水位  y={y_d:.3f}m', dxfattribs={
            'layer': 'WATER_DESIGN', 'height': txt_h * 0.85,
            'insert': (half_w + txt_h * 0.3, y_d*sf),
        })

    # ------ 3. 加大水面线（虚线）------
    if y_i and 0 < y_i < D:
        half_w_i = math.sqrt(max(0, R**2 - (R - y_i)**2)) * sf
        msp.add_line((-half_w_i, y_i*sf), (half_w_i, y_i*sf),
                     dxfattribs={'layer': 'WATER_INCREASED', 'linetype': 'DASHED'})
        msp.add_text(f'▽ 加大水位  y={y_i:.3f}m', dxfattribs={
            'layer': 'WATER_INCREASED', 'height': txt_h * 0.85,
            'insert': (half_w_i + txt_h * 0.3, y_i*sf + txt_h * 0.5),
        })

    # ------ 4. 尺寸标注 ------
    _add_dim_h(msp,
               x1=-R*sf, x2=R*sf,
               y_line=-(gap * 1.1), y_orig=0,
               label=f'D={D:.2f} m',
               txt_h=txt_h, arr=arr, layer='DIMENSION')

    if y_d > 0:
        _add_dim_v(msp,
                   y1=0, y2=y_d*sf,
                   x_line=-(R*sf + gap * 1.4), x_orig=-R*sf,
                   label=f'y={y_d:.3f} m',
                   txt_h=txt_h, arr=arr, layer='DIMENSION')

    if y_d > 0 and FB_d > 0:
        _add_dim_v(msp,
                   y1=y_d*sf, y2=D*sf,
                   x_line=(R*sf + gap * 1.4), x_orig=R*sf,
                   label=f'Fb={FB_d:.3f} m',
                   txt_h=txt_h, arr=arr, layer='DIMENSION')

    msp.add_line((cx, cy), (cx + R*sf * 0.707, cy + R*sf * 0.707),
                 dxfattribs={'layer': 'DIMENSION'})
    msp.add_text(f'R={R:.3f} m', dxfattribs={
        'layer': 'DIMENSION', 'height': txt_h * 0.9,
        'insert': (cx + R*sf * 0.72, cy + R*sf * 0.72),
    })

    # ------ 5. 参数文字块 ------
    text_x = R*sf + gap * 3.5
    inc_str = str(inc_info) if inc_info else ''

    lines = [
        '【明渠水力计算】',
        '断面类型: 圆形',
        '',
        '[输入参数]',
        f'Q = {Q:.3f} m\u00b3/s',
        f'n = {n}',
        f'i = 1/{int(slope_inv)}',
        '',
        '[断面尺寸]',
        f'D = {D:.2f} m',
        f'R = {R:.3f} m',
        '',
        '[设计流量工况]',
        f'y = {y_d:.3f} m',
        f'A = {A_d:.3f} m\u00b2',
        f'V = {V_d:.3f} m/s',
        f'Fb = {FB_d:.3f} m',
        f'净空 = {PA_d:.1f}%',
    ]
    if y_i and y_i > 0:
        lines += [
            '',
            '[加大流量工况]',
            f'加大比例 = {inc_str}',
            f'Q\u589e = {Q_inc:.3f} m\u00b3/s',
            f'y\u589e = {y_i:.3f} m',
            f'V\u589e = {V_i:.3f} m/s',
            f'Fb\u589e = {FB_i:.3f} m',
            f'净空\u589e = {PA_i:.1f}%',
        ]

    lines.insert(1, f'比例: 1:{scale_denom}')
    _add_text_block(msp, text_x, D*sf + txt_h, lines, txt_h, 'TEXT_PARAMS')
