"""按真实桩号区间生成唯一的长度明细，供统计、显示和导出共同使用。"""

import math
if __package__ and __package__.startswith('推求水面线.'):
    from ..utils.numeric_precision import station_millimetres, format_length_station
else:
    from utils.numeric_precision import station_millimetres, format_length_station


_EPS = 1e-8
UNASSIGNED_TYPE = '未划分连接段'


def displayed_length(record):
    """显示长度采用已显示的起止桩号差，保证每行及合计可直接复核。"""
    if 'start_station' in record and 'end_station' in record:
        return (station_millimetres(record['end_station']) - station_millimetres(record['start_station'])) / 1000
    return station_millimetres(record.get('length', 0.0)) / 1000


def is_point_type(structure_type):
    return bool(structure_type) and ('闸' in structure_type or '分水' in structure_type)


def _number(value, label):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{label}不是有效数值') from None
    if not math.isfinite(number):
        raise ValueError(f'{label}不是有限数值')
    return number


def _is_auxiliary(node):
    return bool(getattr(node, 'is_transition', False) or getattr(node, 'is_auto_inserted_channel', False))


def _name(node):
    name = str(getattr(node, 'name', '') or '').strip()
    return '' if name == '-' else name


def _role(node):
    value = getattr(node, 'in_out', '')
    return str(getattr(value, 'value', value) or '')


def build_length_records(nodes, effective_type):
    """将每个真实节点区间拆为实际渐变段、连接段和建筑物本体。

    辅助节点的落位桩号只是绘图/计算位置，不能当作其实际区段边界。
    渐变段取当前采用长度，单个自动连接段取扣除渐变段后的剩余长度。
    无法判明结构的真实空档单列，禁止均分、缩放或修改建筑物边界凑总长。
    """
    if not nodes:
        return []
    real = [i for i, node in enumerate(nodes) if not _is_auxiliary(node)]
    if not real:
        raise ValueError('长度统计缺少真实节点，无法确定起止桩号')
    aliases = {'矩形暗涵': '暗涵-矩形', '矩形暗渠': '暗涵-矩形', '暗渠': '暗涵-矩形'}
    types = [str(effective_type(node) or '') for node in nodes]
    types = [aliases.get(kind, kind) for kind in types]
    stations = {i: _number(getattr(nodes[i], 'station_MC', 0.0), f'第{i + 1}行桩号') for i in real}
    for left, right in zip(real, real[1:]):
        if stations[right] < stations[left]:
            raise ValueError(f'第{left + 1}、{right + 1}行真实节点桩号逆序，无法统计长度')

    # 点状闸不打断同一建筑物；不同名称、类型或新的进出口对必须分开计数。
    groups, owner, previous = {}, {}, None
    for index in real:
        if is_point_type(types[index]):
            continue
        node = nodes[index]
        same = (previous is not None and _name(node) == _name(nodes[previous])
                and types[index] == types[previous]
                and not (_role(nodes[previous]) == '出' and _role(node) == '进'))
        key = owner[previous] if same else f'building:{index}'
        owner[index] = key
        if key not in groups:
            groups[key] = {'name': _name(node) or '(未命名渠段)',
                           'structure_type': types[index] or UNASSIGNED_TYPE,
                           'count_key': key, 'indices': [], 'kind': 'building'}
        groups[key]['indices'].append(index)
        previous = index

    # 闸两侧如果属于同一建筑物，闸所在区间仍归该建筑物本体。
    left_owner, right_owner = {}, {}
    current = None
    for index in real:
        current = owner.get(index, current)
        left_owner[index] = current
    current = None
    for index in reversed(real):
        current = owner.get(index, current)
        right_owner[index] = current

    def base_owner(left, right):
        left_key, right_key = left_owner[left], right_owner[right]
        if left_key and left_key == right_key:
            return groups[left_key]
        for key, node_index, boundary_role in ((left_key, left, '出'), (right_key, right, '进')):
            if key and not _name(nodes[groups[key]['indices'][0]]) and _role(nodes[node_index]) != boundary_role:
                return groups[key]
        left_name = _name(nodes[left]) or '渠段'
        right_name = _name(nodes[right]) or '渠段'
        return {'name': f'连接段({left_name}-{right_name})', 'structure_type': UNASSIGNED_TYPE,
                'count_key': f'gap:{left}:{right}', 'kind': 'unassigned',
                'note': '该区间尚无可确定的结构分界，未计入任何已知建筑物本体'}

    records = []

    def append_piece(source, start, end, node_indices=()):
        if end < start - _EPS:
            raise ValueError('长度统计出现逆序区段，请复核渐变段长度')
        if end <= start:
            return
        record = {key: value for key, value in source.items() if key != 'indices'}
        record.update(start_station=start, end_station=end, length=end - start,
                      node_count=len(node_indices) or 1)
        if (records and records[-1]['count_key'] == record['count_key']
                and records[-1]['end_station'] == start):
            records[-1]['end_station'] = end
            records[-1]['length'] = end - records[-1]['start_station']
        else:
            records.append(record)

    for left, right in zip(real, real[1:]):
        start, end = stations[left], stations[right]
        span = end - start
        auxiliary = list(range(left + 1, right))
        transitions = [i for i in auxiliary if getattr(nodes[i], 'is_transition', False)]
        channels = [i for i in auxiliary if getattr(nodes[i], 'is_auto_inserted_channel', False)
                    and not getattr(nodes[i], 'is_transition', False)]
        lengths = {}
        for index in transitions:
            node = nodes[index]
            value = getattr(node, 'transition_length_override_m', None)
            if value is None:
                value = getattr(node, 'transition_length', 0.0)
                if not value and not getattr(node, 'transition_length_calc_details', None):
                    value = getattr(node, 'stat_length', 0.0)
            length = _number(value, f'第{index + 1}行渐变段长度')
            if length < 0:
                raise ValueError(f'第{index + 1}行渐变段长度为负数')
            lengths[index] = length
        transition_total = math.fsum(lengths.values())
        if transition_total > span + _EPS:
            raise ValueError(f'第{left + 1}至{right + 1}行渐变段合计{transition_total:.6f}m'
                             f'超过实际桩号间距{span:.6f}m')
        remaining = max(0.0, span - transition_total)
        if len(channels) == 1:
            lengths[channels[0]] = remaining
        elif len(channels) > 1:
            for index in channels:
                lengths[index] = _number(getattr(nodes[index], 'stat_length', 0.0), f'第{index + 1}行连接段长度')
                if lengths[index] < 0:
                    raise ValueError(f'第{index + 1}行连接段长度为负数')
            if abs(math.fsum(lengths[i] for i in channels) - remaining) > _EPS:
                raise ValueError(f'第{left + 1}至{right + 1}行含多个连接段，已存分段长度与实际间距不一致')

        base = base_owner(left, right)
        gap_name = f"连接段({_name(nodes[left]) or '渠段'}-{_name(nodes[right]) or '渠段'})"
        cursor = start
        residual_inserted = bool(channels) or remaining <= _EPS
        for index in auxiliary:
            node = nodes[index]
            is_transition = bool(getattr(node, 'is_transition', False))
            # 只有下游是明确进口边界时，进口渐变段才贴靠该边界。
            # 下游为匿名渠道普通IP点时，渐变段贴靠上游出口，余长与后续渠道连续。
            if (not residual_inserted and is_transition
                    and str(getattr(node, 'transition_type', '')) == '进口'
                    and _role(nodes[right]) == '进'):
                append_piece(base, cursor, cursor + remaining, (left, right))
                cursor += remaining
                residual_inserted = True
            length = lengths.get(index, 0.0)
            if length <= 0:
                continue
            source = {'name': gap_name, 'structure_type': '渐变段' if is_transition else types[index],
                      'kind': 'transition' if is_transition else 'connection',
                      'count_key': f'auxiliary:{index}', 'source_node_index': index}
            append_piece(source, cursor, min(end, cursor + length), (index,))
            cursor = min(end, cursor + length)
        if not residual_inserted:
            append_piece(base, cursor, end, (left, right))
        elif end - cursor > _EPS:
            raise ValueError(f'第{left + 1}至{right + 1}行长度统计存在未分配区间')

    # 每个点状建筑物独立计数、长度为零；不把两个相邻闸误算成一个长建筑物。
    for index in real:
        if is_point_type(types[index]):
            records.append({'name': _name(nodes[index]) or '-', 'structure_type': types[index],
                            'kind': 'point', 'count_key': f'point:{index}', 'length': 0.0,
                            'start_station': stations[index], 'end_station': stations[index], 'node_count': 1})
    recorded = {item['count_key'] for item in records}
    for key, group in groups.items():
        if key not in recorded:
            index = group['indices'][0]
            records.append({k: v for k, v in group.items() if k != 'indices'} | {
                'length': 0.0, 'start_station': stations[index], 'end_station': stations[index],
                'node_count': len(group['indices']), 'note': '无独立长度区间，长度为0',
            })
    for item in records:
        group = groups.get(item['count_key'])
        if group:
            item['node_count'] = sum(item['start_station'] <= stations[i] <= item['end_station']
                                     for i in group['indices'])
        item['display_length'] = displayed_length(item)
    records.sort(key=lambda item: (item['start_station'], item['end_station']))
    return records


def summarize_length_records(records):
    """所有类型汇总都从同一份明细生成，名称含“连接”也不能漏计。"""
    grouped = {}
    for index, item in enumerate(records):
        kind = item.get('structure_type') or UNASSIGNED_TYPE
        group = grouped.setdefault(kind, {'keys': set(), 'lengths': [], 'display_mm': 0})
        group['keys'].add(item.get('count_key', f'record:{index}'))
        group['lengths'].append(_number(item.get('length', 0.0), '统计长度'))
        group['display_mm'] += station_millimetres(displayed_length(item))
    return [{'structure_type': kind, 'count': len(group['keys']),
             'total_length': math.fsum(group['lengths']), 'display_total_length': group['display_mm'] / 1000}
            for kind, group in sorted(grouped.items())]


def validate_length_records(nodes, records, summary=None, tolerance=0.001):
    """同时核对总长、逐项桩号差、连续覆盖和各类型归属，不能只验证总和。"""
    real = [node for node in nodes if not _is_auxiliary(node)]
    start = _number(real[0].station_MC, '起点桩号') if real else 0.0
    end = _number(real[-1].station_MC, '终点桩号') if real else start
    canonical = summarize_length_records(records)
    actual = canonical if summary is None else summary
    errors = []
    cursor = start
    for item in sorted(records, key=lambda r: (r['start_station'], r['end_station'])):
        length = _number(item.get('length', 0.0), '统计长度')
        a, b = item['start_station'], item['end_station']
        if length < 0 or abs((b - a) - length) > tolerance:
            errors.append('明细长度与起止桩号不一致')
        if length > 0:
            if abs(a - cursor) > tolerance:
                errors.append('明细存在重复或遗漏区间')
            cursor = b
    if abs(cursor - end) > tolerance:
        errors.append('明细未覆盖完整桩号范围')
    expected = {item['structure_type']: item for item in canonical}
    provided = {item['structure_type']: item for item in actual}
    if set(expected) != set(provided):
        errors.append('明细与汇总的结构类型不一致')
    for kind in set(expected) & set(provided):
        if (abs(expected[kind]['total_length'] - _number(provided[kind].get('total_length', 0.0), '汇总长度')) > tolerance
                or expected[kind]['count'] != provided[kind].get('count')):
            errors.append(f'{kind}的长度或数量与明细不一致')
    total = math.fsum(_number(item.get('total_length', 0.0), '汇总长度') for item in actual)
    diff = abs(total - (end - start))
    if diff > tolerance:
        errors.append('汇总总长与桩号总长不一致')
    return {'ok': 0.0 if errors else 1.0, 'channel_total': end - start,
            'summary_total': total, 'diff': diff, 'errors': errors}
