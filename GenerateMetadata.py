# -*- coding: utf-8 -*-
"""
Generates metadata tags, a summary, and a description for selected feature layers
in the active ArcGIS Pro map. Tags are derived from layer and attribute names,
field types, and repeated values in a sample of records. Existing tags, summary and
description are each preserved unless their own overwrite option is enabled.
For enterprise geodatabase data, an owner connection can be supplied
to write source metadata; otherwise, writable layer metadata is used when
source metadata is read-only.

Target environment: ArcGIS Pro 3.5, Python 3.11.
"""

import os
import re
from collections import Counter
from html import escape

import arcpy

# Parameter configuration (order must match the script tool's parameter order).
# index, name, data type, direction, required, default
PARAMETERS = (
    (0, "Target Features", "GPFeatureLayer (multivalue)", "Input", True, None),
    (1, "Sample Size", "GPLong", "Input", False, 100),
    (2, "Overwrite Existing Tags", "GPBoolean", "Input", False, False),
    (3, "Overwrite Summary", "GPBoolean", "Input", False, False),
    (4, "Overwrite Description", "GPBoolean", "Input", False, False),
    (5, "SQL Server Connection (owner of the data)", "DEWorkspace", "Input", False, None),
)

MAX_TAGS = 30
MAX_TAG_LENGTH = 64
MAX_SAMPLE_VALUE_LENGTH = 40
TOP_VALUES_PER_FIELD = 3
SYSTEM_FIELD_TYPES = {"OID", "Geometry", "Raster", "GlobalID", "Blob", "Guid"}
SYSTEM_FIELD_PATTERN = re.compile(
    r"^(objectid|fid|shape.*|globalid|created_.*|last_edited_.*|editor|creator)$", re.I
)
TYPE_TAGS = {
    "Date": "date fields",
    "DateOnly": "date fields",
    "TimeOnly": "time fields",
    "TimestampOffset": "date fields",
    "Double": "numeric fields",
    "Single": "numeric fields",
    "Integer": "numeric fields",
    "SmallInteger": "numeric fields",
    "BigInteger": "numeric fields",
}


def get_parameters():
    """Read and validate tool parameters."""
    names = [n.strip("'") for n in arcpy.GetParameterAsText(0).split(";") if n.strip()]
    if not names:
        raise ValueError("No target features were supplied.")

    sample_text = arcpy.GetParameterAsText(1)
    sample_size = int(sample_text) if sample_text else PARAMETERS[1][5]
    if sample_size < 1:
        raise ValueError("Sample Size must be 1 or greater.")

    overwrite_tags = arcpy.GetParameterAsText(2).strip().lower() in ("true", "yes", "1")
    overwrite_summary = arcpy.GetParameterAsText(3).strip().lower() in ("true", "yes", "1")
    overwrite_description = arcpy.GetParameterAsText(4).strip().lower() in ("true", "yes", "1")
    connection = arcpy.GetParameterAsText(5).strip().strip("'")
    if connection == "#":
        connection = ""
    if connection and not arcpy.Exists(connection):
        raise ValueError(f"Database connection '{connection}' does not exist.")

    return names, sample_size, overwrite_tags, overwrite_summary, overwrite_description, connection


def find_layers(active_map, names):
    """Return validated feature layers from the active map; warn about the rest."""
    found = []
    seen = set()
    for name in names:
        matches = active_map.listLayers(name) or active_map.listLayers(name.split(".")[-1])
        matches = [m for m in matches if not m.isGroupLayer]
        if not matches:
            arcpy.AddWarning(f"Layer '{name}' not found in the active map. Skipping.")
            continue
        layer = matches[0]
        if not layer.isFeatureLayer:
            arcpy.AddWarning(f"'{name}' is not a feature layer. Skipping.")
            continue
        # arcpy.Exists on a dataSource string is unreliable for enterprise (SDE)
        # layers, so rely on the layer's own state instead.
        if layer.isBroken or not arcpy.Exists(layer):
            arcpy.AddWarning(f"Data source for '{name}' is broken or does not exist. Skipping.")
            continue
        if layer.dataSource in seen:
            arcpy.AddWarning(f"'{name}' shares a data source already queued. Skipping.")
            continue
        seen.add(layer.dataSource)
        found.append(layer)
    return found


def split_words(text):
    """Split snake_case / CamelCase names into lowercase words."""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text.replace("_", " "))
    return " ".join(text.split()).lower()


def sample_text_values(layer, text_fields, sample_size):
    """Return value counts for each text field over a sample of records."""
    counters = {f: Counter() for f in text_fields}
    if not text_fields:
        return counters
    with arcpy.da.SearchCursor(layer, text_fields) as cursor:
        for i, row in enumerate(cursor):
            if i >= sample_size:
                break
            for field, value in zip(text_fields, row):
                if isinstance(value, str):
                    value = value.strip()
                    if 0 < len(value) <= MAX_SAMPLE_VALUE_LENGTH:
                        counters[field][value.lower()] += 1
    return counters


def build_tags(layer, sample_size):
    """Create tags and a profile (for summary/description text) from the layer."""
    tags = [split_words(layer.name)]
    shape_type = getattr(arcpy.Describe(layer), "shapeType", None)
    if shape_type:
        tags.append(f"{shape_type.lower()} features")
    profile = {"shape_type": shape_type, "fields": [], "values": {}}

    fields = [
        f for f in arcpy.ListFields(layer)
        if f.type not in SYSTEM_FIELD_TYPES and not SYSTEM_FIELD_PATTERN.match(f.name)
    ]
    text_fields = []
    for field in fields:
        tags.append(split_words(field.name))
        profile["fields"].append((field.name, field.aliasName, field.type))
        if field.type in TYPE_TAGS:
            tags.append(TYPE_TAGS[field.type])
        elif field.type == "String":
            text_fields.append(field.name)

    for name, counter in sample_text_values(layer, text_fields, sample_size).items():
        # Values repeated across records describe the data; unique values are noise.
        for value, count in counter.most_common(TOP_VALUES_PER_FIELD):
            if count > 1:
                tags.append(value)
                profile["values"].setdefault(name, []).append(value)
    return tags, profile


def build_summary(layer, profile, record_count):
    """Create a one-paragraph summary from the layer profile."""
    shape = (profile["shape_type"] or "").lower()
    kind = f"{shape} feature class" if shape else "table"
    summary = f"{split_words(layer.name).capitalize()}: a {kind}"
    if record_count is not None:
        summary += f" containing {record_count:,} record(s)"
    summary += f" with {len(profile['fields'])} attribute field(s)."
    return summary


def build_description(layer, profile, record_count, sample_size):
    """Create a longer description listing the attributes and common values."""
    # Metadata descriptions render as HTML, so plain newlines collapse; use one <p> per line.
    lines = [build_summary(layer, profile, record_count)]
    if profile["fields"]:
        lines.append("<b>Attributes:</b>")
        for name, alias, _ftype in profile["fields"]:
            label = f"{name} ({alias})" if alias and alias != name else name
            line = label
            values = profile["values"].get(name)
            if values:
                line += " - common values: " + ", ".join(values)
            lines.append(escape(line, quote=False))
    lines.append(
        f"<i>Generated automatically from the field definitions and a sample of up to "
        f"{sample_size} records; review before publishing.</i>"
    )
    return "".join(f"<p>{line}</p>" for line in lines)


def clean_tags(tags):
    """Trim, de-duplicate (case-insensitive) and limit the tags."""
    result = []
    seen = set()
    for tag in tags:
        tag = tag.replace(",", " ").strip()[:MAX_TAG_LENGTH]
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            result.append(tag)
    return result


def resolve_source(layer, connection):
    """Return the path used to open the layer's source metadata.

    For SQL Server (enterprise geodatabase) data, metadata lives in the geodatabase
    and is only editable by the dataset owner, so an owner's .sde connection can be
    supplied to open the dataset through that connection instead of the layer's own.
    """
    if not connection:
        return layer.dataSource
    props = layer.connectionProperties or {}
    dataset = props.get("dataset")
    if not dataset:
        arcpy.AddWarning(f"'{layer.name}' has no dataset name; using its own connection.")
        return layer.dataSource
    path = os.path.join(connection, dataset)
    if not arcpy.Exists(path):
        arcpy.AddWarning(f"'{dataset}' not found through the supplied connection; using the layer's own connection.")
        return layer.dataSource
    return path


def log_connection_user(layer):
    """Report the database user, to help diagnose read-only enterprise metadata."""
    try:
        info = (layer.connectionProperties or {}).get("connection_info", {})
        user = info.get("username") or info.get("user")
        dataset = (layer.connectionProperties or {}).get("dataset", "")
        if user:
            arcpy.AddMessage(f"  Connected as '{user}' to dataset '{dataset}'.")
    except Exception:
        pass


def update_layer_tags(layer, sample_size, overwrite_tags, connection="",
                      overwrite_summary=False, overwrite_description=False):
    """Write generated tags, summary and description. Returns (tag count, target)."""
    md = arcpy.metadata.Metadata(resolve_source(layer, connection))
    if md.isReadOnly:
        log_connection_user(layer)
        arcpy.AddWarning(
            "  Enterprise metadata can only be edited by the dataset owner (e.g. the 'dbo' "
            "user for DBO.* data). Supply an owner connection file to write to the database."
        )
    target = "source"
    if md.isReadOnly:
        # Not the data owner / service or query layer: store tags on the layer in the project.
        arcpy.AddWarning(
            f"Source metadata for '{layer.name}' is read-only; writing to the layer metadata in the project instead."
        )
        md = layer.metadata
        target = "layer"
        if md is None or md.isReadOnly:
            raise RuntimeError("both source and layer metadata are read-only")

    existing = (md.tags or "").split(",") if not overwrite_tags else []
    # Existing tags come first so they are never pushed out by generated ones.
    new_tags, profile = build_tags(layer, sample_size)
    final_tags = clean_tags(existing + new_tags)[:MAX_TAGS]
    md.tags = ", ".join(final_tags)

    # Existing summary/description are only replaced when overwrite is requested.
    write_summary = overwrite_summary or not (md.summary or "").strip()
    write_description = overwrite_description or not (md.description or "").strip()
    if write_summary or write_description:
        try:
            record_count = int(arcpy.management.GetCount(layer).getOutput(0))
        except Exception:
            record_count = None
        if write_summary:
            md.summary = build_summary(layer, profile, record_count)
        if write_description:
            md.description = build_description(layer, profile, record_count, sample_size)
    if target == "layer":
        layer.metadata = md
    else:
        md.save()
    return len(final_tags), target


def main():
    try:
        arcpy.AddMessage("Reading parameters...")
        (names, sample_size, overwrite_tags,
         overwrite_summary, overwrite_description, connection) = get_parameters()

        aprx = arcpy.mp.ArcGISProject("CURRENT")
        active_map = aprx.activeMap
        if active_map is None:
            raise ValueError("No active map. Open a map view and run the tool again.")
        arcpy.env.workspace = aprx.defaultGeodatabase
        arcpy.AddMessage(f"Workspace: {arcpy.env.workspace}")

        arcpy.AddMessage("Validating inputs...")
        layers = find_layers(active_map, names)
        if not layers:
            raise ValueError("None of the supplied layers could be validated.")

        total = len(layers)
        arcpy.AddMessage(f"Updating tags on {total} layer(s); sampling up to {sample_size} records each.")
        arcpy.SetProgressor("step", "Updating metadata tags...", 0, total, 1)
        updated = 0
        layer_level = False
        for i, layer in enumerate(layers, start=1):
            arcpy.SetProgressorLabel(f"Processing {layer.name}")
            try:
                count, target = update_layer_tags(
                    layer, sample_size, overwrite_tags, connection,
                    overwrite_summary, overwrite_description
                )
                updated += 1
                if target == "layer":
                    layer_level = True
                arcpy.AddMessage(f"[{i}/{total}] '{layer.name}': {count} tag(s) written to {target} metadata")
            except arcpy.ExecuteError:
                arcpy.AddWarning(f"[{i}/{total}] '{layer.name}' failed: {arcpy.GetMessages(2)}")
            except Exception as exc:
                arcpy.AddWarning(f"[{i}/{total}] '{layer.name}' failed: {exc}")
            arcpy.SetProgressorPosition()
        arcpy.ResetProgressor()
        if layer_level:
            aprx.save()
            arcpy.AddMessage("Project saved to keep layer-level metadata.")

        arcpy.AddMessage(f"Finished: {updated} of {total} layer(s) updated.")

    except arcpy.ExecuteError:
        arcpy.AddError(arcpy.GetMessages(2))
    except ValueError as exc:
        arcpy.AddError(str(exc))
    except Exception as exc:
        arcpy.AddError(f"Unexpected error: {exc}")


if __name__ == "__main__":
    main()
