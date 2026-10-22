# -*- coding: utf-8 -*-
"""
Script tool (draft): renumber the layer ID (CIM serviceLayerID) of every
layer, including group layers, in the active map, in table-of-contents order.

Tool parameters:
    0  Output Workspace   (Workspace, optional) - receives an old/new ID log table.
                          Defaults to the current project's default geodatabase
                          only when this is left empty.
    1  Starting Layer ID  (Long, optional, default 0)
    2  Log Table Name     (String, optional, default Layer_ID_Log)

Run inside ArcGIS Pro 3.5 (Python 3.11). Save the project to keep the changes.
"""

import os

import arcpy


def get_parameter(index, default=None):
    """Return a tool parameter's text value, or default when empty."""
    value = arcpy.GetParameterAsText(index)
    return value if value else default


def resolve_workspace(aprx, supplied):
    """Use the supplied workspace; fall back to the project geodatabase only if none given."""
    workspace = supplied if supplied else aprx.defaultGeodatabase
    if not workspace or not arcpy.Exists(workspace):
        raise ValueError(f"Output workspace does not exist: {workspace}")
    if supplied:
        arcpy.AddMessage(f"Using supplied output workspace: {workspace}")
    else:
        arcpy.AddMessage(f"No output workspace supplied; using project geodatabase: {workspace}")
    return workspace


def create_log_table(workspace, name):
    """Create the log table and return its path."""
    name = arcpy.ValidateTableName(name, workspace)
    table = arcpy.CreateUniqueName(name, workspace)
    arcpy.management.CreateTable(workspace, os.path.basename(table))
    arcpy.management.AddField(table, "LayerName", "TEXT", field_length=255)
    arcpy.management.AddField(table, "LayerPath", "TEXT", field_length=1024)
    arcpy.management.AddField(table, "OldID", "LONG")
    arcpy.management.AddField(table, "NewID", "LONG")
    return table


def main():
    try:
        aprx = arcpy.mp.ArcGISProject("CURRENT")
        active_map = aprx.activeMap
        if active_map is None:
            raise ValueError("No active map. Open a map view and run the tool again.")

        workspace = resolve_workspace(aprx, get_parameter(0))
        start_id = int(get_parameter(1, "0"))
        if start_id < 0:
            raise ValueError("Starting Layer ID must be 0 or greater.")
        table_name = get_parameter(2, "Layer_ID_Log")

        # listLayers() returns layers in table-of-contents order; group layers get an ID too.
        layers = active_map.listLayers()
        total = len(layers)
        arcpy.AddMessage(f"Active map '{active_map.name}' contains {total} layer(s) to renumber.")
        if total == 0:
            arcpy.AddWarning("No layers found; nothing to do.")
            return

        log_table = create_log_table(workspace, table_name)
        arcpy.AddMessage(f"Created log table: {log_table}")

        arcpy.SetProgressor("step", "Renumbering layers...", 0, total, 1)
        renumbered = 0
        skipped = 0

        with arcpy.da.InsertCursor(
            log_table, ["LayerName", "LayerPath", "OldID", "NewID"]
        ) as cursor:
            for offset, layer in enumerate(layers):
                new_id = start_id + offset
                arcpy.SetProgressorLabel(f"Renumbering {layer.longName}")
                try:
                    cim = layer.getDefinition("V3")
                    old_id = getattr(cim, "serviceLayerID", None)
                    setattr(cim, "serviceLayerID", new_id)
                    layer.setDefinition(cim)
                    cursor.insertRow((layer.name, layer.longName, old_id, new_id))
                    renumbered += 1
                    arcpy.AddMessage(f"[{offset + 1}/{total}] {layer.longName}: {old_id} -> {new_id}")
                except Exception as exc:
                    skipped += 1
                    arcpy.AddWarning(f"[{offset + 1}/{total}] Skipped '{layer.longName}': {exc}")
                arcpy.SetProgressorPosition()

        arcpy.ResetProgressor()
        arcpy.AddMessage(
            f"Finished: {renumbered} renumbered, {skipped} skipped. "
            "Save the project to keep the new layer IDs."
        )

    except arcpy.ExecuteError:
        arcpy.AddError(arcpy.GetMessages(2))
    except Exception as exc:
        arcpy.AddError(f"Layer ID renumbering failed: {exc}")


if __name__ == "__main__":
    main()
