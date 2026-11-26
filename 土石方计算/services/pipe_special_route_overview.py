"""Present all special segments against one independently measured pipe axis."""
from __future__ import annotations

from math import fsum

from .earthwork_scope import _number, trenchless_exclusions, trenchless_method
from .pipe_special_segments import is_special_pipe_object
from .section_scheme_bindings import _root, _route
from .special_pipe_materials import _axis_length, _continuous_pipe_axis_length


def _route_axis(inputs, members, groups):
    if not members or any(part.get("pipe_profile_choice") == "pending_gap" for _, part in members):
        return None, None
    gaps = [after["station_start"] - before["station_end"]
            for (_, before), (_, after) in zip(members, members[1:])]
    if any(gap < -1e-6 for gap in gaps):
        return None, None
    for group in groups:
        if "whole_pipe_axis_length_m" in group:
            return group["whole_pipe_axis_length_m"], group["whole_pipe_axis_basis"]
    try:
        lengths = {id(part): _axis_length(part) for _, part in members}
    except (KeyError, TypeError, ValueError):
        return None, None
    return _continuous_pipe_axis_length(trenchless_exclusions(inputs), members, lengths)


def _known_sum(lengths):
    return fsum(lengths) if all(length is not None for length in lengths) else None


def pipe_special_route_overview(inputs, member_identities, records, *, material_groups=()):
    """Return row and type shares without changing legacy calculation bases.

    ``material_groups`` optionally reuses groups already prepared for these
    exact members. A legacy positioned soil-only record still appears by
    itself; the length-based material which occupies that same capacity is
    counted once in the type and overall material subtotals.
    """
    identities = set(member_identities)
    members = []
    for owner in inputs.get("networks", [inputs]):
        route = _route(owner)
        for part in owner.get("assets", ()):
            if ((route, _root(part)) in identities and is_special_pipe_object(part) and not trenchless_method(part)
                    and part.get("station_start") is not None and part.get("station_end") is not None):
                members.append((owner, part))
    members.sort(key=lambda member: member[1]["station_start"])
    axis_length, axis_basis = _route_axis(inputs, members, material_groups)

    def share(length):
        return (length / axis_length * 100 if length is not None and axis_length and axis_length > 0
                else None)

    lengths, schemes, row_percentages = [], {}, []
    has_soil_only_records = False
    for record in records:
        length = _number(record.get("length"))
        if length is not None and length < 0:
            length = None
        row_percentages.append(share(length))
        if record.get("soil_only"):
            has_soil_only_records = True
            continue
        scheme = record["scheme"]
        _, current = schemes.setdefault(scheme["scheme_id"], (scheme, []))
        current.append(length)
        lengths.append(length)
    scheme_totals = []
    for scheme, values in schemes.values():
        length = _known_sum(values)
        scheme_totals.append({"scheme": scheme, "length_m": length, "percent": share(length)})
    total = _known_sum(lengths)
    return {
        "station_start": members[0][1]["station_start"] if members else None,
        "station_end": max((part["station_end"] for _, part in members), default=None),
        "axis_length_m": axis_length,
        "axis_basis": axis_basis,
        "record_percentages": tuple(row_percentages),
        "schemes": tuple(scheme_totals),
        "special_length_m": total,
        "special_percent": share(total),
        "has_soil_only_records": has_soil_only_records,
    }
