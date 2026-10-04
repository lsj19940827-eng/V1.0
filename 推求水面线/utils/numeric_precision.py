"""需要再次参与计算的数字文本保留原始数值，避免显示往返造成截断。"""

import math
from decimal import Decimal, ROUND_HALF_UP


def format_display_number(value, decimals=2):
    """仅格式化展示文本；计算和保存仍使用原值。"""
    number = float(value)
    text = f'{number:.{decimals}f}'
    if math.isfinite(number) and float(text) == 0:
        return f'{0:.{decimals}f}'
    return text


def format_input_number(value, decimals=3):
    """常规值按指定小数位显示；更多有效位不能因界面格式丢失。"""
    number = float(value)
    if not math.isfinite(number):
        return str(number)
    formatted = f'{number:.{decimals}f}'
    return formatted if float(formatted) == number else str(number)


def station_millimetres(value):
    """先统一到毫米，再拆公里数，避免出现 0+1000.000。"""
    return int((Decimal(str(value)) * 1000).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def format_length_station(value, prefix=''):
    kilometres, millimetres = divmod(station_millimetres(value), 1000000)
    metres, fraction = divmod(millimetres, 1000)
    return f'{prefix}{kilometres}+{metres:03d}.{fraction:03d}'
