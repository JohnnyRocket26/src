import arcpy
import os

# Processing workflow:
# 1. Set the active ArcGIS Pro project's default geodatabase as the workspace.
# 2. Read the RAMM footpaths, repair-state points, and output parameter.
# 3. Calculate the mean Condition value for points contained by each footpath.
# 4. Add or update AVG_Condition and ROUND_Condition on the original feature class.
# 5. Preserve the original polygon features and all existing polygon fields.

def spatial_join_average_points(
    target_polygons, join_points, int_field_name
):
    """
    Adds the average point condition directly to the polygon feature class.
    """
    try:
        arcpy.env.overwriteOutput = True

        average_field_name = f"AVG_{int_field_name}"
        rounded_field_name = f"ROUND_{int_field_name}"
        temporary_join = arcpy.CreateUniqueName(
            "ConditionAverageJoin", arcpy.env.scratchGDB
        )

        if arcpy.Exists(temporary_join):
            arcpy.management.Delete(temporary_join)

        arcpy.AddMessage("Calculating average condition values...")
        field_mappings = arcpy.FieldMappings()
        field_mappings.addTable(target_polygons)
        field_mappings.addTable(join_points)
        field_idx = field_mappings.findFieldMapIndex(int_field_name)

        if field_idx != -1:
            field_map = field_mappings.getFieldMap(field_idx)
            field_map.mergeRule = "Mean"
            out_field = field_map.outputField
            out_field.name = average_field_name
            out_field.aliasName = f"Average of {int_field_name}"
            out_field.type = "Double"
            field_map.outputField = out_field
            field_mappings.replaceFieldMap(field_idx, field_map)
            for map_index in range(field_mappings.fieldCount - 1, -1, -1):
                mapped_field = field_mappings.getFieldMap(map_index).outputField
                if mapped_field.name != out_field.name:
                    field_mappings.removeFieldMap(map_index)
        else:
            raise ValueError(
                f"Field '{int_field_name}' not found in the point feature class."
            )

        arcpy.AddMessage("Calculating polygon averages...")
        arcpy.analysis.SpatialJoin(
            target_features=target_polygons,
            join_features=join_points,
            out_feature_class=temporary_join,
            join_operation="JOIN_ONE_TO_ONE",
            join_type="KEEP_ALL",
            field_mapping=field_mappings,
            match_option="CONTAINS",
        )

        existing_fields = {field.name.upper() for field in arcpy.ListFields(target_polygons)}
        if average_field_name.upper() not in existing_fields:
            arcpy.management.AddField(
                target_polygons,
                average_field_name,
                "DOUBLE",
                field_alias=f"Average of {int_field_name}",
            )
        if rounded_field_name.upper() not in existing_fields:
            arcpy.management.AddField(
                target_polygons,
                rounded_field_name,
                "LONG",
                field_alias=f"Rounded {int_field_name}",
            )

        polygon_oid = arcpy.Describe(target_polygons).OIDFieldName
        averages = {
            row[0]: row[1]
            for row in arcpy.da.SearchCursor(
                temporary_join, ["TARGET_FID", average_field_name]
            )
        }
        with arcpy.da.UpdateCursor(
            target_polygons,
            [polygon_oid, average_field_name, rounded_field_name],
        ) as cursor:
            for row in cursor:
                average_value = averages.get(row[0])
                row[1] = average_value
                row[2] = round(average_value) if average_value is not None else None
                cursor.updateRow(row)

        arcpy.management.Delete(temporary_join)
        arcpy.AddMessage(
            f"Added {average_field_name} and {rounded_field_name} to: {target_polygons}"
        )
        return target_polygons

    except arcpy.ExecuteError:
        arcpy.AddError(arcpy.GetMessages(2))
        raise
    except Exception as e:
        arcpy.AddError(f"An error occurred: {str(e)}")
        raise


if __name__ == "__main__":
    # Define your paths (Update these to match your local data structure)
    arcpy.env.workspace = arcpy.mp.ArcGISProject("CURRENT").defaultGeodatabase

    input_polygons = arcpy.GetParameterAsText(0)
    input_points = arcpy.GetParameterAsText(1)
    output_feature = arcpy.GetParameterAsText(2)

    # The name of the integer field inside the point layer you want to average
    target_field = "Condition"

    # Run the function
    result = spatial_join_average_points(
        target_polygons=input_polygons,
        join_points=input_points,
        int_field_name=target_field,
    )
    arcpy.SetParameterAsText(2, result)
