"""ArcGIS Pro script tool: bridge vulnerability ranking by warming scenario.

Parameters
0. Input bridge feature layer (editable)  - Required, Input, Feature Layer
1. Updated input                          - Derived, Output, Feature Layer
   (set to the input dataset; add as a Derived output parameter)

Appends vuln_rank_0C..3C (Long, 0-100, 100 = most vulnerable) and
vuln_cat_0C..3C (Low / Medium / High) to the input.
"""
# Method:
#   vulnerability = bridge_risk_score (structural, 0-100) x hazard factor,
#   where hazard factor = 'Hazard zone max xC' / 6 (zones 1-6, 6 = most severe).
#   A bridge outside any hazard zone (null/0) is not exposed, so scores 0.
#   Category: rank >= 50 High, >= 25 Medium, otherwise Low.
#   Only selected rows are updated if the layer has a selection.
import arcpy

SCORE_FIELD = 'bridge_risk_score'
SCENARIOS = ['0C', '1C', '2C', '3C']
HAZARD_ALIAS = 'Hazard zone max {}'
OUT_FIELD = 'vuln_rank_{}'
CAT_FIELD = 'vuln_cat_{}'
MAX_ZONE = 6
# Category thresholds on the 0-100 rank: >=HIGH_MIN High, >=MEDIUM_MIN Medium, else Low
HIGH_MIN = 50
MEDIUM_MIN = 25


def find_field(fields, *names):
    """Find a field by name or alias, ignoring case and spaces/underscores."""
    def norm(s):
        return s.lower().replace(' ', '').replace('_', '')
    wanted = {norm(n) for n in names}
    for f in fields:
        if norm(f.name) in wanted or norm(f.aliasName) in wanted:
            return f.name
    raise ValueError(f"Input is missing required field: {names[0]}")


def vulnerability(structural, zone):
    zone = zone or 0  # null hazard zone is treated as 0 (not exposed)
    if structural is None or zone <= 0:
        return 0
    zone = min(zone, MAX_ZONE)
    return int(round(max(0, min(structural, 100)) * zone / MAX_ZONE))


def categorise(rank):
    if rank >= HIGH_MIN:
        return 'High'
    if rank >= MEDIUM_MIN:
        return 'Medium'
    return 'Low'


def main():
    layer = arcpy.GetParameterAsText(0)
    fields = arcpy.ListFields(layer)

    score_f = find_field(fields, SCORE_FIELD)
    hazard_f = {s: find_field(fields, HAZARD_ALIAS.format(s)) for s in SCENARIOS}

    existing = {f.name.lower() for f in fields}
    for s in SCENARIOS:
        if OUT_FIELD.format(s).lower() not in existing:
            arcpy.management.AddField(layer, OUT_FIELD.format(s), 'LONG',
                                      field_alias=f'Vulnerability rank {s}')
        if CAT_FIELD.format(s).lower() not in existing:
            arcpy.management.AddField(layer, CAT_FIELD.format(s), 'TEXT', field_length=20,
                                      field_alias=f'Vulnerability category {s}')
    actual = {f.name.lower(): f.name for f in arcpy.ListFields(layer)}
    out_f = [actual[OUT_FIELD.format(s).lower()] for s in SCENARIOS]
    cat_f = [actual[CAT_FIELD.format(s).lower()] for s in SCENARIOS]

    cols = [score_f] + [hazard_f[s] for s in SCENARIOS] + out_f + cat_f
    updated = 0
    with arcpy.da.UpdateCursor(layer, cols) as cur:
        for row in cur:
            ranks = [vulnerability(row[0], row[1 + i]) for i in range(4)]
            row[5:9] = ranks
            row[9:13] = [categorise(r) for r in ranks]
            cur.updateRow(row)
            updated += 1

    arcpy.SetParameterAsText(1, layer)
    arcpy.AddMessage(f"Updated {updated} bridges with fields: {', '.join(out_f + cat_f)}")


if __name__ == '__main__':
    main()
