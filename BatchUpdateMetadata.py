# Description: Batch update metadata for layers in the active ArcGIS Pro map.
# Summary: Applies provided tags, summary, and description to each layer's source metadata, then saves and synchronizes it.
# Script tool parameters: 0 Layers, 1 Tags, 2 Summary, 3 Description, 4 Append data (Boolean checkbox; unchecked overwrites).

import arcpy


def append_metadata_value(existing_value, new_value, separator):
    """Append a supplied value to existing metadata without duplicating the entire value."""
    new_value = new_value.strip()
    existing_value = (existing_value or "").strip()

    if not new_value or new_value == existing_value:
        return existing_value
    if not existing_value:
        return new_value
    return f"{existing_value}{separator}{new_value}"


def batch_update_metadata():
    # 1. Get user inputs from the ArcGIS Tool dialog
    layer_input = arcpy.GetParameterAsText(0) 
    new_tags = arcpy.GetParameterAsText(1)
    new_summary = arcpy.GetParameterAsText(2)
    new_description = arcpy.GetParameterAsText(3)
    append_parameter = arcpy.GetParameterAsText(4).strip().lower()

    if append_parameter not in {"true", "false"}:
        arcpy.AddError(
            "Append data must be configured as a Boolean checkbox parameter "
            "at index 4 in the script tool."
        )
        return
    append_data = append_parameter == "true"

    # 2. Parse the multiple layers input into a clean list
    layer_list = layer_input.split(";")
    layer_list = [lyr.strip("'") for lyr in layer_list if lyr]

    if not layer_list:
        arcpy.AddWarning("No layers selected.")
        return

    arcpy.AddMessage(f"Found {len(layer_list)} items to process.\n")

    # Access the active project and active map session
    aprx = arcpy.mp.ArcGISProject("CURRENT")
    active_map = aprx.activeMap

    if not active_map:
        arcpy.AddError("[ERROR] There is no active map view open. Please open your map view and run the tool again.")
        return

    # 3. Process each layer string passed by the tool
    for layer_name in layer_list:
        try:
            # Look up the actual layer object inside the active map
            matching_layers = active_map.listLayers(layer_name)
            
            if not matching_layers:
                # If not found directly by name, try checking if it's a short name vs full DBO name
                matching_layers = active_map.listLayers(layer_name.split(".")[-1])

            if not matching_layers:
                arcpy.AddWarning(f"Could not find layer '{layer_name}' in the active map contents. Skipping.")
                continue
            
            # Grab the matched map layer object
            map_layer = matching_layers[0]
            
            # Safely grab the absolute database/catalog path of the source feature class
            desc = arcpy.Describe(map_layer)
            data_path = desc.catalogPath
            
            # Open the metadata directly using its permanent catalog path (forces the DB update)
            md = arcpy.metadata.Metadata(data_path)

            if md.isReadOnly:
                arcpy.AddWarning(f"Metadata for data source of '{layer_name}' is read-only. Skipping.")
                continue

            # Update supplied fields, appending when the checkbox is selected.
            if new_tags:
                md.tags = (
                    append_metadata_value(md.tags, new_tags, ", ")
                    if append_data
                    else new_tags
                )
            if new_summary:
                md.summary = (
                    append_metadata_value(md.summary, new_summary, "\n")
                    if append_data
                    else new_summary
                )
            if new_description:
                md.description = (
                    append_metadata_value(md.description, new_description, "\n")
                    if append_data
                    else new_description
                )

            # Save the metadata permanently to the underlying source
            md.save()
            
            # Explicitly force ArcGIS Pro to refresh and sync the database metadata
            md.synchronize()
            
            arcpy.AddMessage(f"Successfully updated permanent metadata for: {layer_name}")

        except Exception as e:
            arcpy.AddError(f"[ERROR] Failed to update metadata for '{layer_name}': {str(e)}")

    arcpy.AddMessage("\nBatch metadata update complete!")

if __name__ == "__main__":
    batch_update_metadata()
