"""Carry explicit water-profile tunnel construction data into the workbench."""
from copy import deepcopy


TUNNEL_LINING_GEOMETRY_POLICY = "tunnel_source_t0_t_v1"


def uses_explicit_tunnel_base(inputs):
    return any(asset.get("enabled", True) and asset.get("section_type") in {
        "arch_tunnel", "circular_tunnel", "flat_bottom_tunnel", "horseshoe_tunnel"}
        and (asset.get("section") or {}).get("base_thickness") is not None
        for network in inputs.get("networks", []) for asset in network.get("assets", []))


SECTION_FIELDS = {
    "inner_width": ("inner_width", "B"),
    "inner_height": ("inner_height", "H_total"),
    "wall_height": ("wall_height", "H_straight"),
    "arch_angle_degrees": ("arch_angle_degrees", "theta_deg"),
    "lining_thickness": ("lining_thickness", "t"),
    "base_thickness": ("base_thickness", "t0"),
    "wall_thickness_left": ("wall_thickness_left",),
    "wall_thickness_right": ("wall_thickness_right",),
    "roof_thickness": ("roof_thickness",),
    "shotcrete_thickness": ("shotcrete_thickness",),
    "shotcrete_grade": ("shotcrete_grade",),
    "material_grade": ("material_grade",),
    "rock_class": ("rock_class",),
}


def apply_tunnel_lining_option(asset, rock_class):
    """Adopt one explicit source-library class and record the selected values."""
    options = asset.get("source_tunnel_lining_options") or {}
    if rock_class not in options:
        raise ValueError("当前水面线没有该围岩衬砌方案，请重新读取参数库或明确填写厚度")
    section = asset.setdefault("section", {})
    section["rock_class"] = rock_class
    paths = asset.setdefault("source_tunnel_parameter_paths", [])
    for key, alias in (("base_thickness", "t0"), ("lining_thickness", "t")):
        section[key] = deepcopy(options[rock_class][alias])
        path = "section." + key
        if path not in paths:
            paths.append(path)
        asset.setdefault("parameter_sources", {})[path] = "当前水面线围岩衬砌参数库 " + rock_class + "." + alias
    asset["tunnel_lining_selection_mode"] = "source_library"
    asset["source_tunnel_lining_selection_required"] = False


def refresh_tunnel_source_parameters(asset, previous_asset):
    """Reapply the previous class to the newly read library, keeping new source priority."""
    if asset.get("kind") != "tunnel":
        return
    section=asset.setdefault("section",{})
    mode=previous_asset.get("tunnel_lining_selection_mode")
    # A newly filled program default must not hide an earlier explicit local
    # selection when the refreshed source is split back into its edited ranges.
    if mode in {"source_library", "manual"}:
        default_fields = asset.get("tunnel_construction_default_fields") or []
        for key in ("lining_thickness", "base_thickness"):
            path = "section." + key
            if path in default_fields and path not in asset.get("source_tunnel_parameter_paths", []):
                section.pop(key, None)
                default_fields.remove(path)
    if section.get("lining_thickness") is not None and section.get("base_thickness") is not None:
        return
    previous_section=previous_asset.get("section") or {}
    selected=previous_section.get("rock_class")
    options=asset.get("source_tunnel_lining_options") or {}
    if mode == "source_library" and selected in options:
        declared={key:deepcopy(section[key]) for key in ("base_thickness","lining_thickness")
                  if section.get(key) is not None and "section."+key in asset.get("source_tunnel_parameter_paths",[])}
        provenance=deepcopy(asset.get("parameter_sources") or {})
        apply_tunnel_lining_option(asset, selected)
        section.update(declared)
        for key in declared:
            path="section."+key
            if path in provenance:asset["parameter_sources"][path]=provenance[path]
        return
    paths=asset.setdefault("source_tunnel_parameter_paths",[])
    for key in ("base_thickness","lining_thickness"):
        path="section."+key
        if path not in paths:paths.append(path)
        if mode=="manual" and section.get(key) is None and previous_section.get(key) is not None:
            section[key]=deepcopy(previous_section[key])
            asset.setdefault("parameter_sources",{})[path]="用户覆盖：沿用已明确手填的隧洞厚度"
    if mode=="manual" and all(section.get(key) is not None for key in ("base_thickness","lining_thickness")):
        asset["tunnel_lining_selection_mode"]="manual"
        asset["source_tunnel_lining_selection_required"]=False
        for key in ("missing_fields","source_missing_fields"):
            if key in asset:asset[key]=[path for path in asset[key] if path!="section.rock_class"]
    elif mode=="source_library" or asset.get("source_tunnel_lining_selection_required"):
        asset["tunnel_lining_selection_mode"]="pending"
        asset["source_tunnel_lining_selection_required"]=True


def inherit_tunnel_parameters(asset, source_node, source_panel):
    """An unselected rock-class library supplies choices, never an adopted layer."""
    section = asset.setdefault("section", {})
    params = source_node.get("section_params") or {}
    raw_section = source_node.get("section") or {}
    paths = []
    sources = asset.setdefault("parameter_sources", {})
    for target, aliases in SECTION_FIELDS.items():
        for source in (raw_section, params):
            key = next((key for key in aliases if source.get(key) is not None), None)
            if key is not None:
                section[target] = deepcopy(source[key])
                path = "section." + target
                paths.append(path)
                sources[path] = "当前水面线隧洞已填参数 " + key
                break
    construction = asset.setdefault("construction", {})
    for key in ("excavation_clearance", "bedding_thickness", "bedding_width", "bedding_reference"):
        for source in (source_node.get("construction") or {}, params):
            if source.get(key) is not None:
                construction[key] = deepcopy(source[key])
                path = "construction." + key
                paths.append(path)
                sources[path] = "当前水面线隧洞已填参数 " + key
                break
    library = (source_panel.get("extra_caches") or {}).get("custom_rock_lining") or {}
    options = {str(key): deepcopy(value) for key, value in library.items()
               if isinstance(value, dict) and value.get("t0") is not None and value.get("t") is not None}
    asset["source_tunnel_parameters"] = True
    asset["source_tunnel_lining_options"] = options
    selected = options.get(str(section.get("rock_class") or ""))
    if selected:
        for key, alias in (("base_thickness", "t0"), ("lining_thickness", "t")):
            if section.get(key) is None:
                section[key] = deepcopy(selected[alias])
                path = "section." + key
                paths.append(path)
                sources[path] = "当前水面线围岩衬砌参数库 " + section["rock_class"] + "." + alias
    asset["source_tunnel_lining_selection_required"] = bool(options and not selected
        and (section.get("lining_thickness") is None or section.get("base_thickness") is None))
    asset["source_tunnel_parameter_paths"] = paths
    if selected:
        asset["tunnel_lining_selection_mode"] = "source_library"
