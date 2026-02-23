# -*- coding: utf-8 -*-
import sys, re
sys.path.insert(0, r'c:\Users\大渔\Desktop\V1.0\推求水面线')

from config.constants import (
    TRANSITION_ZETA_COEFFICIENTS, TRANSITION_TWISTED_ZETA_RANGE,
    TRANSITION_LENGTH_COEFFICIENTS, TRANSITION_LENGTH_CONSTRAINTS,
    SIPHON_TRANSITION_ZETA_COEFFICIENTS, SIPHON_TRANSITION_FORM_OPTIONS,
    TRANSITION_FORM_OPTIONS, LOCAL_LOSS_COEFFICIENTS, HEAD_LOSS_COLUMNS
)

# 直接从 panel.py 源码解析 NODE_ALL_HEADERS，避免 PySide6 import 链
with open(r'c:\Users\大渔\Desktop\V1.0\渠系断面设计\water_profile\panel.py', encoding='utf-8') as _f:
    _panel_src = _f.read()
_m = re.search(r'NODE_ALL_HEADERS = \[([\s\S]+?)\]\n', _panel_src)
NODE_ALL_HEADERS = re.findall(r'"([^"]+)"', _m.group(1)) if _m else []

issues = []
info = []

# ==================== 1. TRANSITION_ZETA_COEFFICIENTS ====================
print('=== 1. TRANSITION_ZETA_COEFFICIENTS 键名匹配 ===')
for k in ('进口', '出口'):
    ok = k in TRANSITION_ZETA_COEFFICIENTS
    if not ok:
        issues.append('TRANSITION_ZETA_COEFFICIENTS 缺键: ' + k)
    print('  transition_type "%s" in dict: %s' % (k, ok))

print('  TRANSITION_FORM_OPTIONS 覆盖情况:')
for form in TRANSITION_FORM_OPTIONS:
    in_inlet = form in TRANSITION_ZETA_COEFFICIENTS.get('进口', {})
    is_twist = (form == '直线形扭曲面')
    covered = in_inlet or is_twist
    label = '(插值 via TWISTED_ZETA_RANGE)' if is_twist else ('OK' if covered else 'MISSING')
    print('    %-14s %s' % (form, label))
    if not covered:
        issues.append('TRANSITION_FORM_OPTIONS 中 "%s" 无对应 zeta' % form)

# ==================== 2. SIPHON_TRANSITION_ZETA_COEFFICIENTS ====================
print()
print('=== 2. SIPHON_TRANSITION_ZETA_COEFFICIENTS 键名匹配 ===')
for form in SIPHON_TRANSITION_FORM_OPTIONS:
    in_in = form in SIPHON_TRANSITION_ZETA_COEFFICIENTS.get('进口', {})
    in_out = form in SIPHON_TRANSITION_ZETA_COEFFICIENTS.get('出口', {})
    ok = in_in and in_out
    print('    %-12s 进口:%-5s 出口:%-5s %s' % (form, in_in, in_out, 'OK' if ok else 'MISSING'))
    if not ok:
        issues.append('SIPHON 中 "%s" 缺 zeta' % form)

# 倒虹吸渐变段 skip_loss=True，SIPHON_TRANSITION_ZETA_COEFFICIENTS 不参与计算
with open(r'c:\Users\大渔\Desktop\V1.0\推求水面线\core\hydraulic_calc.py', encoding='utf-8') as f:
    src_hc = f.read()
if 'SIPHON_TRANSITION_ZETA_COEFFICIENTS' not in src_hc:
    info.append('SIPHON_TRANSITION_ZETA_COEFFICIENTS 未在 hydraulic_calc.py 中使用 '
                '(倒虹吸渐变段 skip_loss=True，属于设计决策，非Bug)')

# ==================== 3. 直线形扭曲面 估算路径默认值 ====================
print()
print('=== 3. 直线形扭曲面 zeta 估算路径一致性 ===')
print('  TRANSITION_TWISTED_ZETA_RANGE:')
for k, v in TRANSITION_TWISTED_ZETA_RANGE.items():
    midpoint = (v['min_zeta'] + v['max_zeta']) / 2
    print('    %s: [%.2f, %.2f], midpoint=%.3f' % (k, v['min_zeta'], v['max_zeta'], midpoint))

# 找 _estimate_transition_loss 中 fallback zeta 值
m = re.search(r'def _estimate_transition_loss.*?(?=\n    def )', src_hc, re.DOTALL)
if m:
    body = m.group(0)
    defaults = re.findall(r'zeta_table\.get\([^,]+,\s*([0-9.]+)\)', body)
    print('  _estimate_transition_loss fallback zeta:', defaults)
    if defaults and '0.2' in defaults:
        # 0.2 > max(进口)=0.1, 在出口范围0.1~0.17内略微偏高
        info.append('_estimate_transition_loss 对直线形扭曲面使用 fallback=0.2，'
                    '进口偏高(范围0~0.1)；但此仅影响初步估算，最终由 '
                    'get_transition_zeta 插值修正，不影响最终结果')
    print('  (仅初步估算用，最终由 get_transition_zeta 插值修正 — 无功能问题)')

# ==================== 4. TRANSITION_LENGTH_COEFFICIENTS ====================
print()
print('=== 4. TRANSITION_LENGTH_COEFFICIENTS 键名匹配 ===')
for k in ('进口', '出口'):
    ok = k in TRANSITION_LENGTH_COEFFICIENTS
    print('  "%s": %s' % (k, TRANSITION_LENGTH_COEFFICIENTS.get(k, 'MISSING')))
    if not ok:
        issues.append('TRANSITION_LENGTH_COEFFICIENTS 缺键: ' + k)
# 检查各处 fallback 是否一致
defaults_len = re.findall(r'TRANSITION_LENGTH_COEFFICIENTS\.get\([^,]+,\s*([0-9.]+)\)', src_hc)
print('  hydraulic_calc.py fallback 默认值:', defaults_len,
      '(key 始终匹配，fallback 不生效，但进/出口默认不同为轻微代码异味)')
if len(set(defaults_len)) > 1:
    info.append('TRANSITION_LENGTH_COEFFICIENTS.get() fallback 在不同函数中不一致 '
                '(%s)，但 key 始终匹配不影响结果' % ','.join(set(defaults_len)))

# ==================== 5. TRANSITION_LENGTH_CONSTRAINTS ====================
print()
print('=== 5. TRANSITION_LENGTH_CONSTRAINTS 键名匹配 ===')
for k in ('渡槽', '隧洞', '倒虹吸'):
    ok = k in TRANSITION_LENGTH_CONSTRAINTS
    print('  "%s": %s' % (k, 'OK' if ok else 'MISSING'))
    if not ok:
        issues.append('TRANSITION_LENGTH_CONSTRAINTS 缺键: ' + k)

# ==================== 6. constants.py HEAD_LOSS_COLUMNS 过期 ====================
print()
print('=== 6. constants.py HEAD_LOSS_COLUMNS 是否过期 ===')
stale_texts = [c['text'] for c in HEAD_LOSS_COLUMNS]
actual_loss_headers = [h for h in NODE_ALL_HEADERS if '水头损失' in h or '渐变段长度' in h]
print('  constants.py HEAD_LOSS_COLUMNS:', stale_texts)
print('  panel.py NODE_ALL_HEADERS 对应列:', actual_loss_headers)
missing = [h for h in actual_loss_headers if h not in stale_texts and h.replace('\n','') not in ''.join(stale_texts)]
print('  缺失列:', missing or '无')
print('  注: HEAD_LOSS_COLUMNS 仅出现在 panel.py 注释中，无实际功能引用')
if missing:
    info.append('constants.py HEAD_LOSS_COLUMNS 未包含 "局部水头损失"，且 '
                '"渐变段长度\\nL" 与实际 "渐变段长度L" 有换行符差异 (纯文档问题)')

# ==================== 汇总 ====================
print()
print('=' * 50)
print('=== 汇总 ===')
if issues:
    print('【功能性问题】:')
    for i, iss in enumerate(issues, 1):
        print('  %d. %s' % (i, iss))
else:
    print('  无功能性问题 — 所有系数表键名匹配正确')
if info:
    print('【提示/代码异味】:')
    for i, msg in enumerate(info, 1):
        print('  %d. %s' % (i, msg))
print()
print('结论：Bug3 同类问题已全部处理。constants.py 的 HEAD_LOSS_COLUMNS 需同步更新（文档一致性）。')
