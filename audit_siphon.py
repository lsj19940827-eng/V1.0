# -*- coding: utf-8 -*-
# 全面审查 default_project.siphon.json 中所有倒虹吸的纵断面数据状态
import json

with open('渠系断面设计/default_project.siphon.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

siphons = data['siphons']
print(f"共 {len(siphons)} 个倒虹吸\n")
print(f"{'名称':<12} {'is_example':<12} {'纵断面段数':<10} {'nodes数':<8} {'需修复'}")
print("-" * 55)

need_fix = []
for name, s in siphons.items():
    is_example = s.get('longitudinal_is_example', None)
    long_segs = sum(1 for seg in s.get('segments', []) if seg.get('direction') == '纵断面')
    nodes = len(s.get('longitudinal_nodes', []))
    # 判断是否有问题：is_example=False 且有纵断面段或节点
    problem = (is_example == False) and (long_segs > 0 or nodes > 0)
    print(f"{name:<12} {str(is_example):<12} {long_segs:<10} {nodes:<8} {'⚠ 需修复' if problem else 'OK'}")
    if problem:
        need_fix.append(name)

print(f"\n需要修复的倒虹吸: {need_fix}")

