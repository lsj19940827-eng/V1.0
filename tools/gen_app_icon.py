# -*- coding: utf-8 -*-
"""
生成渠系水力计算系统应用图标（.ico）

设计：在 512px 高分辨率绘制 → LANCZOS 缩放到各尺寸
  - 蓝色圆角方形背景
  - 粗线条白色梯形渠道断面（简洁清晰）
  - 浅蓝水面填充
  - 底部白色"渠"字
"""

from PIL import Image, ImageDraw, ImageFont
import os, math

BASE = 512  # 基准绘制尺寸


def create_base_icon():
    """在 512x512 高分辨率绘制基础图标"""
    s = BASE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")
    
    margin = int(s * 0.03)
    r = int(s * 0.17)
    
    # ── 1. 圆角方形背景 ──
    draw.rounded_rectangle(
        [margin, margin, s - margin, s - margin],
        radius=r, fill=(0, 110, 210, 255)
    )
    
    # ── 2. 梯形渠道断面（粗白线） ──
    cx = s // 2
    top_w = int(s * 0.56)
    bot_w = int(s * 0.26)
    trap_h = int(s * 0.30)
    trap_top = int(s * 0.18)
    
    pts = [
        (cx - top_w // 2, trap_top),
        (cx + top_w // 2, trap_top),
        (cx + bot_w // 2, trap_top + trap_h),
        (cx - bot_w // 2, trap_top + trap_h),
    ]
    
    lw = int(s * 0.03)  # 粗线条，小尺寸也看得清
    draw.line([pts[0], pts[3]], fill="white", width=lw, joint="curve")
    draw.line([pts[3], pts[2]], fill="white", width=lw, joint="curve")
    draw.line([pts[2], pts[1]], fill="white", width=lw, joint="curve")
    
    # ── 3. 水面填充 ──
    water_y = int(trap_top + trap_h * 0.45)
    ratio_w = (water_y - trap_top) / trap_h
    wl = int(cx - top_w // 2 + ratio_w * (top_w // 2 - bot_w // 2))
    wr = int(cx + top_w // 2 - ratio_w * (top_w // 2 - bot_w // 2))
    
    # 填充多边形：水面线 → 左斜边 → 底边 → 右斜边
    water_poly = [
        (wl + lw // 2, water_y),
        (pts[3][0] + lw // 2, pts[3][1] - lw // 3),
        (pts[2][0] - lw // 2, pts[2][1] - lw // 3),
        (wr - lw // 2, water_y),
    ]
    draw.polygon(water_poly, fill=(140, 200, 255, 160))
    
    # 水面波浪线
    wave_pts = []
    for xi in range(wl, wr + 1, 2):
        t = (xi - wl) / max(1, wr - wl)
        wy = water_y + math.sin(t * math.pi * 3) * (s * 0.012)
        wave_pts.append((xi, int(wy)))
    if len(wave_pts) > 1:
        draw.line(wave_pts, fill=(255, 255, 255, 200), width=int(s * 0.014))
    
    # ── 4. "渠" 字 ──
    text = "渠"
    text_size = int(s * 0.24)
    font = None
    for font_path in ["C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyh.ttc",
                       "msyhbd.ttc", "msyh.ttc"]:
        try:
            font = ImageFont.truetype(font_path, text_size)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
    
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (s - tw) // 2
    ty = int(s * 0.62)
    draw.text((tx, ty), text, fill="white", font=font)
    
    return img


def main():
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "推求水面线", "resources")
    os.makedirs(output_dir, exist_ok=True)
    
    icon_path = os.path.join(output_dir, "app_icon.ico")
    
    # 在 512px 绘制一次，然后 LANCZOS 高质量缩放到各尺寸
    base = create_base_icon()
    
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = []
    for sz in sizes:
        resized = base.resize((sz, sz), Image.LANCZOS)
        images.append(resized)
    
    # 保存为 .ico（多尺寸嵌入）
    images[-1].save(icon_path, format="ICO",
                    sizes=[(sz, sz) for sz in sizes],
                    append_images=images[:-1])
    print(f"图标已生成: {icon_path}")
    
    # 预览
    preview_path = os.path.join(output_dir, "app_icon_preview.png")
    base.resize((256, 256), Image.LANCZOS).save(preview_path, format="PNG")
    print(f"预览已生成: {preview_path}")


if __name__ == "__main__":
    main()
