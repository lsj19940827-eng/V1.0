# -*- coding: utf-8 -*-
"""共享数据模块（供 PySide6 新版使用）"""

from .shared_data_manager import get_shared_data_manager
from .k12_images_data import get_k12_image_bytes

__all__ = ['get_shared_data_manager', 'get_k12_image_bytes']
