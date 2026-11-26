"""从同一冻结TIN收敛施工辅助上下界，不让远处高点撑大当前沟槽。"""
from copy import deepcopy
from .construction_templates import prepare_assets
from .contracts import ConstructionInputError, finite_number


def derive_local_domains(assets, settings, terrain, query_bounds):
    result = deepcopy(assets)
    initial = prepare_assets(result, settings)
    limits = {}
    for asset in initial:
        if not asset.get("enabled", True):
            continue
        construction = asset["construction"]
        limits[asset["asset_id"]] = []
        for section in asset["geometry_sections"]:
            low = section["trench_floor_z"]
            high = max(p[1] for ring in section["permanent"] for p in ring)
            if construction["target_mode"] == "finished_profile":
                elevations = [finite_number(p[1], "显式完成面高程") for p in construction["target_profile"]]
                low, high = min(low, min(elevations)), max(high, max(elevations))
            elif construction["target_mode"] == "union_terrain":
                high = max(high, max(p[1] for ring in section["target"] for p in ring))
            for side in ("left", "right"):
                stages = construction.get("excavation_stages_" + side) or []
                high = max(high, section["trench_floor_z"] + sum(
                    finite_number(stage["height"], "中间坡级高") for stage in stages[:-1]))
            limits[asset["asset_id"]].append({"station": section["station"],
                "base_z": low - 1., "clip_top_z": high + 1.})
    margin = max(float(settings.get("linear_tolerance", .001)), 1e-8)
    required_clearance = max(.05, 10 * float(settings.get("tolerance_m", margin)))
    expansion_padding = max(1., 2 * required_clearance)
    last_bounds = None
    for iteration in range(1, 33):
        for asset in result:
            if asset["asset_id"] in limits:
                asset["calculation_domain_sections"] = deepcopy(limits[asset["asset_id"]])
        prepared = prepare_assets(result, settings)
        boxes, owners = [], []
        for asset in prepared:
            if not asset.get("enabled", True):
                continue
            sections = asset["geometry_sections"]
            for index, pair in enumerate(zip(sections, sections[1:])):
                xy = [(section["origin"][0] + section["lateral"][0] * point[0],
                       section["origin"][1] + section["lateral"][1] * point[0])
                      for section in pair for ring in section["domain"] for point in ring]
                boxes.append([min(p[0] for p in xy)-margin, min(p[1] for p in xy)-margin,
                              max(p[0] for p in xy)+margin, max(p[1] for p in xy)+margin])
                owners.append((asset["asset_id"], index))
        bounds = query_bounds(boxes)
        if not isinstance(bounds, list) or len(bounds) != len(boxes):
            raise ConstructionInputError("原生TIN局部范围回复数量不完整")
        changed = False
        for owner, bound in zip(owners, bounds):
            identity, index = owner
            if not isinstance(bound, dict):
                raise ConstructionInputError(f"{identity} 第{index+1}施工区间缺少真实地形覆盖")
            low = finite_number(bound.get("min_z"), "局部TIN最低高程")
            high = finite_number(bound.get("max_z"), "局部TIN最高高程")
            if low > high:
                raise ConstructionInputError("原生TIN局部高程上下界颠倒")
            for item in limits[identity][index:index+2]:
                new_base = min(item["base_z"], low - expansion_padding) if item["base_z"] > low - required_clearance else item["base_z"]
                new_top = max(item["clip_top_z"], high + expansion_padding) if item["clip_top_z"] < high + required_clearance else item["clip_top_z"]
                changed |= new_base != item["base_z"] or new_top != item["clip_top_z"]
                item.update(base_z=new_base, clip_top_z=new_top)
        last_bounds = bounds
        if not changed:
            for asset in result:
                if asset["asset_id"] in limits:
                    asset["calculation_domain_sections"] = deepcopy(limits[asset["asset_id"]])
                    asset["calculation_domain_basis"] = {
                        "method": "fixed_TIN_XY_box_linear_clip_monotone_envelope",
                        "mesh_sha256": terrain["mesh_sha256"], "iterations": iteration,
                        "expansion_padding_m": expansion_padding, "required_vertical_clearance_m": required_clearance,
                        "xy_margin_m": margin,
                        "not_design_elevation": True,
                        "bounds": [{**deepcopy(bound),
                                    "lower_clearance_m": bound["min_z"] - max(
                                        limits[owner[0]][owner[1]]["base_z"], limits[owner[0]][owner[1]+1]["base_z"]),
                                    "upper_clearance_m": min(
                                        limits[owner[0]][owner[1]]["clip_top_z"], limits[owner[0]][owner[1]+1]["clip_top_z"]) - bound["max_z"]}
                                   for owner, bound in zip(owners, last_bounds) if owner[0] == asset["asset_id"]]}
            return result
    raise ConstructionInputError("真实TIN施工辅助范围32轮仍未稳定，请核对地形与施工边坡；未生成工程量")
