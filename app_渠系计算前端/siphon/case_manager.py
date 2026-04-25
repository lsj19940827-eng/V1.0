# -*- coding: utf-8 -*-
"""倒虹吸工况管理器"""
import os
import json
import time
from typing import List, Dict, Optional

class CaseInfo:
    """工况信息"""
    def __init__(self, name: str, file_path: str, created_time: float, order: int):
        self.name = name
        self.file_path = file_path
        self.created_time = created_time
        self.order = order  # 用户自定义排序

class CaseManager:
    """工况管理器"""
    def __init__(self, cases_dir: str):
        self.cases_dir = cases_dir
        os.makedirs(cases_dir, exist_ok=True)
        self.cases: List[CaseInfo] = []
        self._load_cases()

    def _load_cases(self):
        """加载所有工况"""
        self.cases = []
        if not os.path.exists(self.cases_dir):
            return

        for fname in os.listdir(self.cases_dir):
            if fname.endswith('.siphon.json'):
                fpath = os.path.join(self.cases_dir, fname)
                try:
                    with open(fpath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    name = data.get('case_name', fname.replace('.siphon.json', ''))
                    created = data.get('created_time', os.path.getctime(fpath))
                    order = data.get('order', created)
                    self.cases.append(CaseInfo(name, fpath, created, order))
                except:
                    pass

        self.cases.sort(key=lambda c: c.order)

    def create_case(self, name: Optional[str] = None) -> CaseInfo:
        """创建新工况"""
        if name is None:
            name = self._generate_name()

        fpath = os.path.join(self.cases_dir, f"{name}.siphon.json")
        created = time.time()
        order = created

        data = {'case_name': name, 'created_time': created, 'order': order}
        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        case = CaseInfo(name, fpath, created, order)
        self.cases.append(case)
        return case

    def import_case_file(self, source_path: str) -> CaseInfo:
        """导入工况文件，兼容旧版“导出参数”JSON。"""
        self._load_cases()
        data = self._read_import_case_data(source_path)
        raw_name = data.get('case_name') or data.get('name') or self._name_from_path(source_path)
        name = self._unique_import_name(self._clean_case_name(raw_name))
        now = time.time()

        data['case_name'] = name
        data['created_time'] = now
        data['order'] = now

        file_path = os.path.join(self.cases_dir, f"{name}.siphon.json")
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        self._load_cases()
        for case in self.cases:
            if os.path.abspath(case.file_path) == os.path.abspath(file_path):
                return case
        case = CaseInfo(name, file_path, now, now)
        self.cases.append(case)
        return case

    def _read_import_case_data(self, source_path: str) -> Dict:
        """读取导入文件，并把旧参数备份包装拆成工况数据。"""
        with open(source_path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            raise ValueError("工况文件格式不正确")

        wrapped_data = payload.get('data')
        if isinstance(wrapped_data, dict):
            return dict(wrapped_data)
        return dict(payload)

    @staticmethod
    def _name_from_path(source_path: str) -> str:
        """从文件名推导工况名称。"""
        fname = os.path.basename(source_path)
        if fname.endswith('.siphon.json'):
            return fname[:-len('.siphon.json')]
        return os.path.splitext(fname)[0]

    @staticmethod
    def _clean_case_name(name: str) -> str:
        """清理为可保存的工况名称。"""
        invalid_chars = '<>:"/\\|?*'
        cleaned = ''.join(
            '_' if ch in invalid_chars or ord(ch) < 32 else ch
            for ch in str(name or '').strip()
        ).strip(' .')
        return cleaned or "工况"

    def _unique_import_name(self, base_name: str) -> str:
        """避免导入工况与现有工况重名。"""
        existing_names = {case.name for case in self.cases}
        if base_name not in existing_names and not os.path.exists(
                os.path.join(self.cases_dir, f"{base_name}.siphon.json")):
            return base_name

        idx = 1
        while True:
            suffix = "_导入" if idx == 1 else f"_导入{idx}"
            candidate = f"{base_name}{suffix}"
            if candidate not in existing_names and not os.path.exists(
                    os.path.join(self.cases_dir, f"{candidate}.siphon.json")):
                return candidate
            idx += 1

    def _generate_name(self) -> str:
        """生成工况名称"""
        i = 1
        while True:
            name = f"工况{i}"
            if not any(c.name == name for c in self.cases):
                return name
            i += 1

    def rename_case(self, case: CaseInfo, new_name: str):
        """重命名工况"""
        old_path = case.file_path
        new_path = os.path.join(self.cases_dir, f"{new_name}.siphon.json")

        with open(old_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        data['case_name'] = new_name

        with open(new_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        if old_path != new_path:
            os.remove(old_path)

        case.name = new_name
        case.file_path = new_path

    def delete_case(self, case: CaseInfo):
        """删除工况"""
        if os.path.exists(case.file_path):
            os.remove(case.file_path)
        self.cases.remove(case)

    def duplicate_case(self, case: CaseInfo) -> CaseInfo:
        """复制工况"""
        new_name = f"{case.name}_副本"
        i = 1
        while any(c.name == new_name for c in self.cases):
            new_name = f"{case.name}_副本{i}"
            i += 1

        with open(case.file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        created = time.time()
        data['case_name'] = new_name
        data['created_time'] = created
        data['order'] = created

        new_path = os.path.join(self.cases_dir, f"{new_name}.siphon.json")
        with open(new_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        new_case = CaseInfo(new_name, new_path, created, created)
        self.cases.append(new_case)
        return new_case

    def reorder_cases(self, new_order: List[CaseInfo]):
        """重新排序工况"""
        for i, case in enumerate(new_order):
            case.order = i
            with open(case.file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            data['order'] = i
            with open(case.file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        self.cases = new_order

    def save_case_data(self, case: CaseInfo, data: dict):
        """保存工况数据"""
        data['case_name'] = case.name
        data['created_time'] = case.created_time
        data['order'] = case.order
        with open(case.file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_case_data(self, case: CaseInfo) -> dict:
        """加载工况数据"""
        with open(case.file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
