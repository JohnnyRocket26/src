"""ArcGIS Pro script tool: append maximum flood hazard zone fields to building footprints.
Parameters
0. Building footprints (Feature Layer, polygon)        - Required, Input (edited in place)
1. Flood hazard zone tables (Table View, multivalue)   - Required, Input
2. Updated building footprints (Feature Layer)         - Derived, Output
Each hazard table must have a COMPKEY field and a MAX_gridcode field; the buildings must have COMPKEY.
Workflow:
  1. For each hazard table, read MAX_gridcode by COMPKEY (highest value if a COMPKEY repeats).
  2. Add one SHORT field per table to the buildings, named after the table (reused if it already exists).
  3. Set each field by COMPKEY. Buildings with no matching COMPKEY, or a NULL value, are left NULL.
The input is modified in place, so back it up first.
"""
import os
import arcpy

KEY_FIELD = "COMPKEY"
VALUE_FIELD = "MAX_gridcode"


def find_field(table, name):
    """Return the actual field name matching `name` (or its alias) case-insensitively."""
    fields = arcpy.ListFields(table)
    for f in fields:
        if f.name.lower() == name.lower():
            return f.name
    for f in fields:
        if (f.aliasName or "").lower() == name.lower():
            return f.name
    # Joined layers prefix field names, e.g. "CommunityFacility.COMPKEY"
    for f in fields:
        if f.name.lower().endswith("." + name.lower()):
            return f.name
    available = ", ".join(f.name for f in fields)
    raise ValueError(f"Field '{name}' not found in {table}. Available fields: {available}")


def norm_key(value):
    """Normalise keys so text and numeric COMPKEY fields still match."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip() or None


def parse_tables(text):
    """Split a multivalue parameter string, respecting quoted paths that contain ';'."""
    items, cur, quote = [], "", None
    for ch in text:
        if quote:
            if ch == quote:
                quote = None
            else:
                cur += ch
        elif ch in "'\"":
            quote = ch
        elif ch == ";":
            items.append(cur)
            cur = ""
        else:
            cur += ch
    items.append(cur)
    return [i.strip() for i in items if i.strip()]


def read_zones(table):
    """Return {COMPKEY: highest MAX_gridcode} from a hazard table."""
    key_f = find_field(table, KEY_FIELD)
    val_f = find_field(table, VALUE_FIELD)
    zones = {}
    seen = set()
    repeated = set()
    with arcpy.da.SearchCursor(table, [key_f, val_f]) as cur:
        for key, val in cur:
            key = norm_key(key)
            if key is None:
                continue
            if key in seen:
                repeated.add(key)
            seen.add(key)
            if val is None:
                continue
            if key not in zones or val > zones[key]:
                zones[key] = val
    if repeated:
        sample = ", ".join(sorted(repeated)[:10])
        more = " ..." if len(repeated) > 10 else ""
        arcpy.AddWarning(f"{table}: {len(repeated)} {KEY_FIELD} value(s) repeat; "
                         f"the highest {VALUE_FIELD} is used. Repeated: {sample}{more}")
    return zones


def main():
    buildings = arcpy.GetParameterAsText(0)
    tables = parse_tables(arcpy.GetParameterAsText(1))

    desc = arcpy.Describe(buildings)
    if desc.shapeType != "Polygon":
        raise ValueError("Building footprints must be a polygon feature class.")
    if not tables:
        raise ValueError("At least one flood hazard zone table is required.")
    # Cursors cannot update a joined layer, so edit the underlying feature class instead
    if any("." in f.name for f in arcpy.ListFields(buildings)):
        buildings = desc.catalogPath
        desc = arcpy.Describe(buildings)
        arcpy.AddWarning(f"Input layer is joined; updating the source feature class: {buildings}")
    bld_key = find_field(buildings, KEY_FIELD)
    workspace = desc.path

    existing = {f.name.lower(): f for f in arcpy.ListFields(buildings)}
    used_new = set()
    targets = []  # (field name, {COMPKEY: value})
    for table in tables:
        zones = read_zones(table)
        base = os.path.splitext(os.path.basename(table))[0]
        name = arcpy.ValidateFieldName(base, workspace)
        # Avoid collisions between new fields derived from similarly named tables
        i = 1
        while name.lower() in used_new:
            suffix = f"_{i}"
            name = arcpy.ValidateFieldName(base, workspace)[:64 - len(suffix)] + suffix
            i += 1
        used_new.add(name.lower())

        if name.lower() in existing:
            field = existing[name.lower()]
            if field.type not in ("SmallInteger", "Integer", "Double", "Single"):
                raise ValueError(f"Existing field '{field.name}' is not numeric.")
            name = field.name
            arcpy.AddWarning(f"Field '{name}' already exists and will be overwritten.")
        else:
            arcpy.management.AddField(buildings, name, "SHORT")
        arcpy.AddMessage(f"{table}: {len(zones)} {KEY_FIELD} value(s) -> field '{name}'")
        targets.append((name, zones))

    fields = [bld_key] + [t[0] for t in targets]
    total = int(arcpy.management.GetCount(buildings)[0])
    step = max(1, total // 10)
    matched = [0] * len(targets)
    with arcpy.da.UpdateCursor(buildings, fields) as cur:
        for n, row in enumerate(cur, 1):
            key = norm_key(row[0])
            for i, (_, zones) in enumerate(targets):
                val = zones.get(key)
                if val is not None:
                    val = int(val)
                    matched[i] += 1
                row[i + 1] = val
            cur.updateRow(row)
            if n % step == 0:
                arcpy.AddMessage(f"{int(100 * n / total)}% complete")

    for (name, _), count in zip(targets, matched):
        arcpy.AddMessage(f"{name}: {count} of {total} building(s) matched")
    arcpy.SetParameterAsText(2, buildings)


if __name__ == "__main__":
    main()
