"""ArcGIS Pro script tool: classify building flood level from a flood level table.
Parameters
0. Building footprints (Feature Layer, polygon)  - Required, Input (edited in place)
1. Flood level table (Table View)                - Required, Input
2. Flood level field (Field, from parameter 1)   - Required, numeric, default "MEAN"
3. New field name (String)                       - Required, default "FLOOD_LEVEL"
4. Updated building footprints (Feature Layer)   - Derived, Output
Both inputs must have a COMPKEY field and the table must have the chosen numeric flood level field.
Workflow:
  1. Read the flood level field from the flood table for each COMPKEY. If a COMPKEY appears more than
     once, the highest value is used (most conservative).
  2. Add a text field to the buildings (reused if it already exists).
  3. Set it by COMPKEY: LOW (< 0.2), MEDIUM (0.2 to 0.3), HIGH (> 0.3).
     Buildings with no matching COMPKEY, or a NULL value, are left NULL.
The input is modified in place, so back it up first.
"""
import arcpy
KEY_FIELD = "COMPKEY"
DEFAULT_VALUE_FIELD = "MEAN"
LOW_MAX = 0.2
MEDIUM_MAX = 0.3
def find_field(table, name):
    """Return the actual field name matching `name` case-insensitively."""
    for f in arcpy.ListFields(table):
        if f.name.lower() == name.lower():
            return f.name
    raise ValueError(f"Field '{name}' not found in {table}")
def norm_key(value):
    """Normalise keys so text and numeric COMPKEY fields still match."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip() or None
def classify(mean):
    if mean < LOW_MAX:
        return "LOW"
    if mean <= MEDIUM_MAX:
        return "MEDIUM"
    return "HIGH"
def read_levels(table, value_field):
    """Return {COMPKEY: highest value} from the flood level table."""
    key_f = find_field(table, KEY_FIELD)
    val_f = find_field(table, value_field)
    levels = {}
    with arcpy.da.SearchCursor(table, [key_f, val_f]) as cur:
        for key, mean in cur:
            key = norm_key(key)
            if key is None or mean is None:
                continue
            if key not in levels or mean > levels[key]:
                levels[key] = mean
    return levels
def main():
    buildings = arcpy.GetParameterAsText(0)
    flood_table = arcpy.GetParameterAsText(1)
    value_field = arcpy.GetParameterAsText(2) or DEFAULT_VALUE_FIELD
    new_field = arcpy.GetParameterAsText(3) or "FLOOD_LEVEL"
    desc = arcpy.Describe(buildings)
    if desc.shapeType != "Polygon":
        raise ValueError("Building footprints must be a polygon feature class.")
    bld_key = find_field(buildings, KEY_FIELD)
    levels = read_levels(flood_table, value_field)
    arcpy.AddMessage(f"Read flood levels for {len(levels)} {KEY_FIELD} value(s).")
    if not levels:
        arcpy.AddWarning("No usable flood level records found; the new field will be empty.")
    workspace = desc.path
    new_field = arcpy.ValidateFieldName(new_field, workspace)
    existing = {f.name.lower(): f for f in arcpy.ListFields(buildings)}
    if new_field.lower() in existing:
        new_field = existing[new_field.lower()].name
        if existing[new_field.lower()].type != "String":
            raise ValueError(f"Existing field '{new_field}' is not a text field.")
        arcpy.AddWarning(f"Field '{new_field}' already exists and will be overwritten.")
    else:
        arcpy.management.AddField(buildings, new_field, "TEXT", field_length=10)
    total = int(arcpy.management.GetCount(buildings)[0])
    step = max(1, total // 10)
    counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, None: 0}
    with arcpy.da.UpdateCursor(buildings, [bld_key, new_field]) as cur:
        for n, (key, _) in enumerate(cur, 1):
            mean = levels.get(norm_key(key))
            level = classify(mean) if mean is not None else None
            counts[level] += 1
            cur.updateRow([key, level])
            if n % step == 0:
                arcpy.AddMessage(f"{int(100 * n / total)}% complete")
    arcpy.AddMessage(f"LOW: {counts['LOW']}, MEDIUM: {counts['MEDIUM']}, "
                     f"HIGH: {counts['HIGH']}, no match/NULL: {counts[None]}")
    arcpy.SetParameterAsText(4, buildings)
if __name__ == "__main__":
    main()
