# -*- coding: utf-8 -*-
"""静态检查生产代码的类内覆盖和领域层依赖，不导入应用或算法模块。"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path


PRODUCTION_DIRECTORIES = (
    "app_渠系计算前端", "calc_渠系计算算法内核", "推求水面线", "倒虹吸水力计算系统",
)
PURE_DIRECTORIES = (
    "calc_渠系计算算法内核", "推求水面线/core", "推求水面线/models",
    "推求水面线/managers", "推求水面线/shared", "推求水面线/utils",
    "倒虹吸水力计算系统",
)
# 这些数据适配模块暂保留原路径；只能依赖此列表中的其他纯模块。
PURE_FRONTEND_MODULES = frozenset({
    "app_渠系计算前端.batch.calculation_service",
    "app_渠系计算前端.batch.schema",
    "app_渠系计算前端.batch.engines",
    "app_渠系计算前端.increase_input_helper",
    "app_渠系计算前端.project_codec",
    "app_渠系计算前端.project_session",
    "app_渠系计算前端.report_meta_model",
})
GUI_NAMESPACES = ("PySide", "PyQt", "qfluentwidgets", "tkinter", "Tkinter", "wx")
GUI_BACKENDS = ("matplotlib.backends.backend_qt", "matplotlib.backends.backend_tk",
                "matplotlib.backends.backend_wx")


@dataclass(frozen=True)
class ArchitectureIssue:
    path: str
    line: int
    rule: str
    message: str


def _property_chain(name, methods):
    """property 的 getter/setter/deleter 是合法的同名描述符组合。"""
    first = methods[0]
    if not any(isinstance(d, ast.Name) and d.id == "property" for d in first.decorator_list):
        return False
    return all(any(
        isinstance(d, ast.Attribute) and d.attr in {"getter", "setter", "deleter"}
        and isinstance(d.value, ast.Name) and d.value.id == name
        for d in method.decorator_list
    ) for method in methods[1:])


def _is_overload(method):
    return any((isinstance(d, ast.Name) and d.id == "overload")
               or (isinstance(d, ast.Attribute) and d.attr == "overload")
               for d in method.decorator_list)


def _module_name(path):
    parts = list(Path(path).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _pure_kind(path):
    normalized = Path(path).as_posix()
    if _module_name(normalized) in PURE_FRONTEND_MODULES:
        return "frontend_data"
    if normalized == "atomic_json.py":
        return "domain"
    if any(normalized.startswith(prefix + "/") for prefix in PURE_DIRECTORIES):
        return "domain"
    return None


def _import_modules(node, path):
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        if node.level:
            parts = list(Path(path).parent.parts)
            up = node.level - 1
            if up:
                parts = parts[:-up]
            prefix = ".".join(parts)
            module = ".".join(part for part in (prefix, node.module or "") if part)
        else:
            module = node.module or ""
        # from package import child 同时检查子模块，以免相对导入绕过边界。
        return [module if alias.name == "*" else f"{module}.{alias.name}" for alias in node.names]
    if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
        function = node.func
        dynamic = ((isinstance(function, ast.Name) and function.id in {"__import__", "import_module"})
                   or (isinstance(function, ast.Attribute) and function.attr == "import_module"))
        if dynamic and isinstance(node.args[0].value, str):
            return [node.args[0].value]
    return []


def _forbidden_dependency(module, kind):
    if module.startswith(GUI_NAMESPACES) or module.startswith(GUI_BACKENDS):
        return True
    if module == "app_渠系计算前端" or module.startswith("app_渠系计算前端."):
        if kind == "domain":
            return True
        # 允许 from 纯模块 import 数据类，但不允许导入其相邻 UI 模块。
        return not any(module == pure or module.startswith(pure + ".")
                       for pure in PURE_FRONTEND_MODULES)
    return False


def check_source(source: str, path: str) -> list[ArchitectureIssue]:
    """检查给定源码，便于回归测试与其他工具复用。"""
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as error:
        return [ArchitectureIssue(path, error.lineno or 1, "syntax", str(error.msg))]
    issues = []
    for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
        methods = defaultdict(list)
        for node in cls.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods[node.name].append(node)
        for name, definitions in methods.items():
            if len(definitions) < 2 or _property_chain(name, definitions):
                continue
            if all(_is_overload(method) for method in definitions[:-1]) and not _is_overload(definitions[-1]):
                continue
            locations = ", ".join(str(method.lineno) for method in definitions)
            issues.append(ArchitectureIssue(path, definitions[-1].lineno, "duplicate-method",
                                            f"{cls.name}.{name} 重复定义，位置：{locations}"))
    kind = _pure_kind(path)
    if kind:
        for node in ast.walk(tree):
            forbidden = [module for module in _import_modules(node, path)
                         if _forbidden_dependency(module, kind)]
            if forbidden:
                issues.append(ArchitectureIssue(path, node.lineno, "domain-ui-import",
                                                f"纯数据/算法模块依赖界面：{forbidden[0]}"))
    return issues


def production_files(root: Path):
    """默认检查全部生产目录和根目录模块，不扫描测试、工具及历史构建目录。"""
    files = list(root.glob("*.py"))
    for directory in PRODUCTION_DIRECTORIES:
        folder = root / directory
        if folder.exists():
            files.extend(path for path in folder.rglob("*.py")
                         if not any(part in {"__pycache__", "build", "dist", ".venv"}
                                    for part in path.relative_to(folder).parts))
    return sorted(set(files))


def check_paths(root: Path, paths=None):
    files = production_files(root) if paths is None else [root / path for path in paths]
    issues = []
    for file in files:
        relative = file.relative_to(root).as_posix()
        try:
            source = file.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as error:
            issues.append(ArchitectureIssue(relative, 1, "read", str(error)))
            continue
        issues.extend(check_source(source, relative))
    return files, sorted(issues, key=lambda issue: (issue.path, issue.line, issue.rule))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="可选的仓库相对路径；默认全扫生产代码")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json", action="store_true", help="输出机器可读结果")
    arguments = parser.parse_args(argv)
    root = arguments.root.resolve()
    files, issues = check_paths(root, arguments.paths or None)
    if arguments.json:
        print(json.dumps({"files_checked": len(files), "issues": [asdict(issue) for issue in issues]},
                         ensure_ascii=False, indent=2))
    else:
        for issue in issues:
            print(f"{issue.path}:{issue.line}: [{issue.rule}] {issue.message}")
        print(f"架构检查：{len(files)} 个生产文件，{len(issues)} 项问题")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
