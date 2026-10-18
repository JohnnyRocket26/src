# -*- coding: utf-8 -*-
"""
Script tool (draft): record source metadata for multiple layers in the active map
into an output table.

Target environment: ArcGIS Pro 3.5, Python 3.11.
Relative output names are created in the current project's default geodatabase.
"""

import os
from typing import Literal

import arcpy

# Parameter configuration (order must match the script tool's parameter order).
# index, name, data type, direction, required
PARAMETERS = (
    (0, "Target Features", "GPFeatureLayer (multivalue)", "Input", True),
    (1, "Output Table", "DETable", "Output", True),
)

# Output fields: name, type, length (None when not text)
OUTPUT_FIELDS: tuple[tuple[str, Literal["TEXT", "SHORT"], int | None], ...] = (
    ("LayerName", "TEXT", 255),
    ("SourcePath", "TEXT", 1024),
    ("DataType", "TEXT", 50),
    ("Title", "TEXT", 255),
    ("Tags", "TEXT", 1024),
    ("Summary", "TEXT", 2048),
    ("Description", "TEXT", 8000),
    ("Credits", "TEXT", 1024),
    ("UseLimits", "TEXT", 2048),
    ("HasMetadata", "SHORT", None),
)


def text_value(value, limit):
    """Return a metadata value as text truncated to the field length."""
    return (value or "").strip()[:limit]


def parse_layer_names(raw):
    """Split a multivalue parameter string into layer names."""
    return [item.strip("'") for item in raw.split(";") if item.strip()]


def resolve_output_table(aprx, output):
    """Place a bare table name in the project geodatabase; keep full paths as given."""
    if not output:
        raise ValueError("An output table is required.")
    if os.path.dirname(output):
        workspace = os.path.dirname(output)
        if not arcpy.Exists(workspace):
            raise ValueError(f"Output workspace does not exist: {workspace}")
        return output
    workspace = aprx.defaultGeodatabase
    if not workspace or not arcpy.Exists(workspace):
        raise ValueError(f"Project default geodatabase not found: {workspace}")
    return os.path.join(workspace, arcpy.ValidateTableName(output, workspace))


def find_layers(active_map, names):
    """Return (name, layer) pairs for names found in the map; warn about the rest."""
    found = []
    for name in names:
        matches = active_map.listLayers(name) or active_map.listLayers(name.split(".")[-1])
        matches = [m for m in matches if not m.isGroupLayer]
        if matches:
            found.append((name, matches[0]))
        else:
            arcpy.AddWarning(f"Layer '{name}' not found in the active map. Skipping.")
    return found


def create_output_table(table):
    """Create the output table with the metadata fields."""
    workspace, name = os.path.split(table)
    arcpy.management.CreateTable(workspace, name)
    for field, ftype, length in OUTPUT_FIELDS:
        if length:
            arcpy.management.AddField(table, field, ftype, field_length=length)
        else:
            arcpy.management.AddField(table, field, ftype)


def read_row(layer):
    """Build one output row from a layer's source metadata."""
    source = layer.dataSource
    md = arcpy.metadata.Metadata(source)
    has_md = 1 if any((md.title, md.tags, md.summary, md.description)) else 0
    return (
        text_value(layer.name, 255),
        text_value(source, 1024),
        text_value(getattr(arcpy.Describe(layer), "dataType", ""), 50),
        text_value(md.title, 255),
        text_value(md.tags, 1024),
        text_value(md.summary, 2048),
        text_value(md.description, 8000),
        text_value(md.credits, 1024),
        text_value(md.accessConstraints, 2048),
        has_md,
    )


def main():
    try:
        arcpy.AddMessage("Reading parameters...")
        raw_layers = arcpy.GetParameterAsText(0)
        raw_output = arcpy.GetParameterAsText(1)

        names = parse_layer_names(raw_layers)
        if not names:
            raise ValueError("No target features were supplied.")

        aprx = arcpy.mp.ArcGISProject("CURRENT")
        active_map = aprx.activeMap
        if active_map is None:
            raise ValueError("No active map. Open a map view and run the tool again.")

        arcpy.AddMessage("Validating inputs...")
        layers = find_layers(active_map, names)
        valid = []
        for name, layer in layers:
            if layer.isFeatureLayer and arcpy.Exists(layer.dataSource):
                valid.append((name, layer))
            else:
                arcpy.AddWarning(f"Source for '{name}' does not exist or is not a feature layer. Skipping.")
        if not valid:
            raise ValueError("None of the supplied layers could be validated.")

        output_table = resolve_output_table(aprx, raw_output)
        if arcpy.Exists(output_table) and not arcpy.env.overwriteOutput:
            raise ValueError(f"Output table already exists (overwrite is off): {output_table}")
        if arcpy.Exists(output_table):
            arcpy.management.Delete(output_table)

        arcpy.AddMessage(f"Creating output table: {output_table}")
        create_output_table(output_table)

        total = len(valid)
        arcpy.SetProgressor("step", "Recording metadata...", 0, total, 1)
        recorded = 0
        field_names = [f[0] for f in OUTPUT_FIELDS]
        with arcpy.da.InsertCursor(output_table, field_names) as cursor:
            for i, (_, layer) in enumerate(valid, start=1):
                arcpy.SetProgressorLabel(f"Reading {layer.name}")
                try:
                    cursor.insertRow(read_row(layer))
                    recorded += 1
                    arcpy.AddMessage(f"[{i}/{total}] Recorded metadata for '{layer.name}'")
                except Exception as exc:
                    arcpy.AddWarning(f"[{i}/{total}] Failed for '{layer.name}': {exc}")
                arcpy.SetProgressorPosition()
        arcpy.ResetProgressor()

        arcpy.SetParameterAsText(1, output_table)
        arcpy.AddMessage(f"Finished: {recorded} of {total} layer(s) recorded.")

    except arcpy.ExecuteError:
        arcpy.AddError(arcpy.GetMessages(2))
    except ValueError as exc:
        arcpy.AddError(str(exc))
    except Exception as exc:
        arcpy.AddError(f"Unexpected error: {exc}")


if __name__ == "__main__":
    main()
