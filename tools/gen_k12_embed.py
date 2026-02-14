# -*- coding: utf-8 -*-
"""生成 K.1.2 示意图嵌入数据模块"""
from PIL import Image
import os, io, base64

d = r'C:\Users\大渔\Desktop\V1.0\倒虹吸水力计算系统\resources\渐变段图片'
names = ['曲线形反弯扭曲面', '直线形扭曲面', '圆弧直墙', '八字形', '直角形']
out_path = r'C:\Users\大渔\Desktop\V1.0\推求水面线\ui\k12_images_data.py'

lines = []
lines.append('# -*- coding: utf-8 -*-')
lines.append('"""')
lines.append('表K.1.2 渐变段示意图 - 嵌入式图片数据')
lines.append('图片已压缩为 JPEG 格式并 base64 编码，无需依赖外部图片文件。')
lines.append('"""')
lines.append('')
lines.append('import base64')
lines.append('import io')
lines.append('')
lines.append('')
lines.append('# 各型式示意图的 base64 编码数据')
lines.append('_K12_IMAGE_DATA = {')

for name in names:
    img = Image.open(os.path.join(d, f'{name}.png')).convert('RGB')
    ratio = 800 / img.width
    new_h = int(img.height * ratio)
    img = img.resize((800, new_h), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode('ascii')
    # 每行76字符拼接
    chunks = [b64[i:i+76] for i in range(0, len(b64), 76)]
    lines.append(f'    "{name}": (')
    for chunk in chunks:
        lines.append(f'        "{chunk}"')
    lines.append('    ),')

lines.append('}')
lines.append('')
lines.append('')
lines.append('def get_k12_image_bytes(form_name: str) -> bytes:')
lines.append('    """获取指定型式的示意图原始字节数据"""')
lines.append('    b64_str = _K12_IMAGE_DATA.get(form_name, "")')
lines.append('    if not b64_str:')
lines.append('        return b""')
lines.append('    return base64.b64decode(b64_str)')
lines.append('')
lines.append('')
lines.append('def get_k12_pil_image(form_name: str):')
lines.append('    """获取指定型式的示意图 PIL Image 对象，找不到返回 None"""')
lines.append('    data = get_k12_image_bytes(form_name)')
lines.append('    if not data:')
lines.append('        return None')
lines.append('    try:')
lines.append('        from PIL import Image')
lines.append('        return Image.open(io.BytesIO(data))')
lines.append('    except Exception:')
lines.append('        return None')
lines.append('')

with open(out_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))

print(f'Generated: {out_path}')
print(f'File size: {os.path.getsize(out_path) // 1024} KB')
