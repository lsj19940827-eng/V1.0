# -*- coding: utf-8 -*-
import json

with open('渠系断面设计/default_project.siphon.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

siphons = data['siphons']
targets = ['1#', '2#', '3#', '4#', '5#', '6#', '7#', '8#']

for name in targets:
    if name not in siphons:
        print(f'[WARN] {name} not found')
        continue
    s = siphons[name]
    segs_before = len(s.get('segments', []))
    long_segs_before = sum(1 for seg in s.get('segments', []) if seg.get('direction') == '纵断面')
    nodes_before = len(s.get('longitudinal_nodes', []))
    flag_before = s.get('longitudinal_is_example')

    # 只保留通用构件段（移除所有纵断面管身段）
    s['segments'] = [seg for seg in s.get('segments', []) if seg.get('direction') == '通用']
    # 清空纵断面节点
    s['longitudinal_nodes'] = []
    # 标记为示例数据
    s['longitudinal_is_example'] = True
    # 清空旧计算结果（纵断面数据已变，结果无意义）
    s['total_head_loss'] = None
    s['diameter'] = None
    s['calculated_at'] = ''

    segs_after = len(s['segments'])
    print(f'{name}: segments {segs_before}->{segs_after} (移除{long_segs_before}个纵断面段), '
          f'nodes {nodes_before}->0, flag {flag_before}->True')

with open('渠系断面设计/default_project.siphon.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print('\n写入完成。')

