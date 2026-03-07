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
