# -*- coding: utf-8 -*-
"""补丁发布安全策略，供构建、正式发版和回补脚本共用。"""

MAX_PATCH_DELETED_COUNT = 100
MAX_PATCH_TOTAL_COVERAGE = 300
DEFAULT_MAX_PATCH_TO_FULL_RATIO = 0.70


def _float_value(value, default: float = 0.0) -> float:
    """将策略输入里的数字字段转换成浮点数。"""
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def _missing_source_versions(
    patch_result: dict,
    expected_source_versions: list[str] | tuple[str, ...] | None,
) -> list[str]:
    """找出补丁未覆盖的基线版本。"""
    expected = [str(v) for v in (expected_source_versions or []) if str(v).strip()]
    if not expected:
        return []
    actual = {
        str(v).strip()
        for v in (patch_result or {}).get("source_versions", [])
        if str(v).strip()
    }
    return [version for version in expected if version not in actual]


def should_skip_universal_patch(
    patch_result: dict,
    *,
    full_size_mb: float = 0,
    expected_source_versions: list[str] | tuple[str, ...] | None = None,
    max_patch_to_full_ratio: float = DEFAULT_MAX_PATCH_TO_FULL_RATIO,
) -> tuple[bool, str]:
    """根据补丁覆盖范围和大小判断是否应跳过补丁发布。"""
    changed_count = int((patch_result or {}).get("changed_count", 0) or 0)
    deleted_count = int((patch_result or {}).get("deleted_count", 0) or 0)
    size_mb = _float_value((patch_result or {}).get("size_mb", 0))
    effective_full_size_mb = _float_value(
        full_size_mb
        or (patch_result or {}).get("full_size_mb")
        or (patch_result or {}).get("full_package_size_mb")
    )

    if deleted_count > MAX_PATCH_DELETED_COUNT:
        return (
            True,
            f"覆盖范围过大：deleted_count={deleted_count}，超过 {MAX_PATCH_DELETED_COUNT}",
        )

    total_coverage = changed_count + deleted_count
    if total_coverage > MAX_PATCH_TOTAL_COVERAGE:
        return (
            True,
            f"覆盖范围过大：changed+deleted={total_coverage}，超过 {MAX_PATCH_TOTAL_COVERAGE}",
        )

    missing_versions = _missing_source_versions(patch_result, expected_source_versions)
    if missing_versions:
        return True, f"补丁来源版本不完整，缺少基线：{', '.join(missing_versions)}"

    if effective_full_size_mb > 0 and size_mb > 0:
        if size_mb >= effective_full_size_mb:
            return (
                True,
                f"补丁包不小于完整包：size_mb={size_mb:.2f}，"
                f"完整包={effective_full_size_mb:.2f}",
            )
        ratio = size_mb / effective_full_size_mb
        if ratio >= max_patch_to_full_ratio:
            return (
                True,
                f"补丁包接近完整包：size_mb={size_mb:.2f}，"
                f"完整包={effective_full_size_mb:.2f}，"
                f"比例={ratio:.0%}，超过 {max_patch_to_full_ratio:.0%}",
            )

    return False, ""
