# -*- coding: utf-8 -*-
import arcpy
from sys import argv

def run_createRoutes(centerlines_layer, search_radius):
    """Core logic to create routes using passed parameters."""
    arcpy.AddMessage("Executing route creation script logic...")

    # Processing workflow:
    # 1. Create and populate From_measure, To_measure, and UID2 on Centerlines.
    # 2. Create route features from the centerline line layer.
    # 3. Generate points spaced at 0.5 meters along those route lines.
    # 4. Locate each point along the route to calculate route measure values.
    # 5. Convert the point records into a route event layer.
    # 6. Spatially join the route events to the inspection condition line layer.
    # 7. Export records with NULL condition values, then remove them from the sorted output.
    # 8. Apply condition symbology and add the sorted layer to the active map.
    def set_symbol_outline_no_color(symbol):
        symbol.outlineColor = {"RGB": [0, 0, 0, 0]}
        symbol.outlineWidth = 0
    def apply_condition_symbology(layer_name, field_name="condition"):
        """
        Apply unique value symbology for condition:
        1=Medium Apple, 2=Solar Yellow, 3=Electron Gold, 4=Mars Red, 5=Amethyst.
        """
        try:
            aprx = arcpy.mp.ArcGISProject("CURRENT")
            active_map = aprx.activeMap
            layer = None
            for lyr in active_map.listLayers():
                if lyr.name == layer_name and lyr.isFeatureLayer:
                    layer = lyr
                    break
            if layer is None:
                arcpy.AddWarning(f"Layer '{layer_name}' not found in active map.")
                return
            field_names = [f.name.lower() for f in arcpy.ListFields(layer)]
            if field_name.lower() not in field_names:
                arcpy.AddWarning(
                    f"Field '{field_name}' not found in layer '{layer_name}'. "
                    f"Available fields: {', '.join(field_names)}"
                )
                return
            sym = layer.symbology
            sym.updateRenderer("UniqueValueRenderer")
            sym.renderer.fields = [field_name]
            color_map = {
                "1": {"RGB": [141, 182, 0, 100]},
                "2": {"RGB": [255, 238, 88, 100]},
                "3": {"RGB": [255, 193, 7, 100]},
                "4": {"RGB": [165, 42, 42, 100]},
                "5": {"RGB": [153, 102, 204, 100]},
            }
            for group in sym.renderer.groups:
                for item in group.items:
                    raw_val = None
                    if item.values and len(item.values) > 0 and len(item.values[0]) > 0:
                        raw_val = item.values[0][0]
                    value_text = str(raw_val).strip() if raw_val is not None else ""
                    if value_text.endswith(".0"):
                        value_text = value_text[:-2]
                    if value_text in color_map:
                        item.symbol.color = color_map[value_text]
                        item.label = value_text
                    else:
                        item.symbol.color = {"RGB": [200, 200, 200, 25]}
                    set_symbol_outline_no_color(item.symbol)
            layer.symbology = sym
            arcpy.AddMessage(
                f"Applied condition symbology to '{layer_name}' "
                f"on field '{field_name}'"
            )
        except Exception as exc:
            arcpy.AddWarning(
                f"Could not apply condition symbology to "
                f"'{layer_name}': {str(exc)}"
            )
    def prepare_centerline_route_fields(centerlines):
        """Populate the route-measure fields and a unique numeric identifier."""
        field_names = {field.name.lower() for field in arcpy.ListFields(centerlines)}
        for field_name, field_type in [
            ("From_measure", "FLOAT"),
            ("To_measure", "FLOAT"),
            ("UID2", "LONG"),
        ]:
            if field_name.lower() not in field_names:
                arcpy.management.AddField(centerlines, field_name, field_type)
        arcpy.management.CalculateField(centerlines, "From_measure", "0", "PYTHON3")
        arcpy.management.CalculateField(
            centerlines, "To_measure", "!Shape_Length!", "PYTHON3"
        )
        arcpy.management.CalculateField(
            centerlines,
            "UID2",
            "generate_numeric_id(!OBJECTID!, !Shape_Length!)",
            "PYTHON3",
            code_block="""import hashlib
    def generate_numeric_id(val1, val2, length=6):
        combined = f"{val1}{val2}"
        hash_obj = hashlib.md5(combined.encode())
        return int(hash_obj.hexdigest(), 16) % (10**length)
    """,
        )
        arcpy.AddMessage(
            "Prepared From_measure, To_measure, and UID2 fields on Centerlines."
        )
    def RouteCreation(
        Search_Radius="4 Meters", Centerlines="Centerlines"
    ):  # Step 2 Route creation model
        # Grab the active project's default geodatabase automatically
        arcpy.env.workspace = arcpy.mp.ArcGISProject("CURRENT").defaultGeodatabase
        arcpy.env.overwriteOutput = True  # Avoids 'dataset already exists' crashes
        arcpy.ImportToolbox(
            r"c:\program files\arcgis\pro\Resources\ArcToolbox\toolboxes\Data Management Tools.tbx"
        )
        Route_Identifier_Field = "UID2"
        Measure_Source = "TWO_FIELDS"
        From_Measure_Field = "From_measure"
        To_Measure_Field = "To_measure"
        Route_Identifier_Field_3_ = "UID2"
        Point_Placement = "DISTANCE"
        Distance = "0.5 Meters"
        Include_end_points = True
        Add_accumulated_distance_and_sequence_fields = True
        Route_Identifier_Field_2_ = "UID2"
        Use_M_direction_offsetting = False
        FootpathInspectionExport = f"{arcpy.env.workspace}/FootpathInspectionExport"
        Match_Option = "CLOSEST"
        Sort_Field = [["RID", "ASCENDING"], ["MEAS", "ASCENDING"]]
        # Process: Create Routes (Create Routes) (lr)
        CenterlineRoute = "in_memory/CenterlineRoutes"
        # Add these lines right before arcpy.lr.CreateRoutes
        arcpy.AddMessage(
            f"Evaluated Input: {Centerlines.__str__().format(**locals(),**globals()) if isinstance(Centerlines, str) else Centerlines}"
        )
        arcpy.AddMessage(f"Evaluated Output: {CenterlineRoute}")
        prepare_centerline_route_fields(Centerlines)
        arcpy.lr.CreateRoutes(
            in_line_features=Centerlines,
            route_id_field=Route_Identifier_Field,
            out_feature_class=CenterlineRoute,
            measure_source=Measure_Source,
            from_measure_field=From_Measure_Field,
            to_measure_field=To_Measure_Field,
        )
        # Process: Generate Points Along Lines (Generate Points Along Lines) (management)
        Footpath_points = "in_memory/FootpathPoints"
        arcpy.management.GeneratePointsAlongLines(
            Input_Features=(
                Centerlines.__str__().format(**locals(), **globals())
                if isinstance(Centerlines, str)
                else Centerlines
            ),
            Output_Feature_Class=Footpath_points,
            Point_Placement=Point_Placement,
            Distance=Distance,
            Include_End_Points=Include_end_points,
            Add_Chainage_Fields=Add_accumulated_distance_and_sequence_fields,
        )
        # Process: Locate Features Along Routes (Locate Features Along Routes) (lr)
        CreateRouteEventTbl = "in_memory/CreateRouteEventsTbl"
        arcpy.lr.LocateFeaturesAlongRoutes(
            in_features=Footpath_points,
            in_routes=CenterlineRoute,
            route_id_field=Route_Identifier_Field_2_,
            radius_or_tolerance="0 Meters",
            out_table=CreateRouteEventTbl,
            out_event_properties="RID; Point; MEAS",
            m_direction_offsetting=Use_M_direction_offsetting,
        )
        # Process: Make Route Event Layer (Make Route Event Layer) (lr)
        FootpathRouteEvents = "in_memory/FootpathRouteEvents"
        arcpy.lr.MakeRouteEventLayer(
            in_routes=CenterlineRoute,
            route_id_field=Route_Identifier_Field_3_,
            in_table=CreateRouteEventTbl,
            in_event_properties="rid; Point; meas",
            out_layer=FootpathRouteEvents,
        )
        # Process: Spatial Join (Spatial Join) (analysis)
        FootpathRouteEventCondition = "in_memory/FootpathRouteEventCondition"
        arcpy.analysis.SpatialJoin(
            target_features=FootpathRouteEvents,
            join_features=FootpathInspectionExport,
            out_feature_class=FootpathRouteEventCondition,
            field_mapping='RID "RID" true true false 4 Long 0 0,First,#,FootpathRouteEvents,RID,-1,-1;MEAS "MEAS" true true false 0 Double 0 0,First,#,FootpathRouteEvents,MEAS,-1,-1;Distance "Distance" true true false 0 Double 0 0,First,#,FootpathRouteEvents,Distance,-1,-1;ORIG_FID "ORIG_FID" true true false 255 Long 0 0,First,#,FootpathRouteEvents,ORIG_FID,-1,-1;ORIG_LEN "ORIG_LEN" true true false 255 Double 0 0,First,#,FootpathRouteEvents,ORIG_LEN,-1,-1;ORIG_SEQ "ORIG_SEQ" true true false 255 Long 0 0,First,#,FootpathRouteEvents,ORIG_SEQ,-1,-1;InPoly_ID "InPoly_ID" true true false 4 Long 0 0,First,#,FootpathRouteEvents,InPoly_ID,-1,-1;InPoly_FID "InPoly_FID" true true false 4 Long 0 0,First,#,FootpathRouteEvents,InPoly_FID,-1,-1;InLine_ID "InLine_ID" true true false 4 Long 0 0,First,#,FootpathRouteEvents,InLine_ID,-1,-1;InLine_FID "InLine_FID" true true false 4 Long 0 0,First,#,FootpathRouteEvents,InLine_FID,-1,-1;MIN_WIDTH "MIN_WIDTH" true true false 8 Double 0 0,First,#,FootpathRouteEvents,MIN_WIDTH,-1,-1;MAX_WIDTH "MAX_WIDTH" true true false 8 Double 0 0,First,#,FootpathRouteEvents,MAX_WIDTH,-1,-1;AVG_WIDTH "AVG_WIDTH" true true false 8 Double 0 0,First,#,FootpathRouteEvents,AVG_WIDTH,-1,-1;COLLAPSED "COLLAPSED" true true false 4 Long 0 0,First,#,FootpathRouteEvents,COLLAPSED,-1,-1;Shape_Length "Shape_Length" true true false 8 Double 0 0,First,#,FootpathRouteEvents,Shape_Length,-1,-1;To_measure "To_measure" true true false 4 Float 0 0,First,#,FootpathRouteEvents,To_measure,-1,-1;UID "UID" true true false 4 Long 0 0,First,#,FootpathRouteEvents,UID,-1,-1;From_measure "From_measure" true true false 4 Float 0 0,First,#,FootpathRouteEvents,From_measure,-1,-1;esrignss_avg_h_rms "Average horizontal accuracy (m)" true true false 8 Double 0 0,First,#,L:/ESRI_Projects/Roading/Footpaths/Monowai footpath condition/Monowai footpath condition.gdb/FootpathInspectionExport,esrignss_avg_h_rms,-1,-1;globalid "globalid" false false true 38 GlobalID 0 0,First,#,L:/ESRI_Projects/Roading/Footpaths/Monowai footpath condition/Monowai footpath condition.gdb/FootpathInspectionExport,globalid,-1,-1;created_user "created_user" true true true 255 Text 0 0,First,#,L:/ESRI_Projects/Roading/Footpaths/Monowai footpath condition/Monowai footpath condition.gdb/FootpathInspectionExport,created_user,0,254;created_date "created_date" true true true 8 Date 0 1,First,#,L:/ESRI_Projects/Roading/Footpaths/Monowai footpath condition/Monowai footpath condition.gdb/FootpathInspectionExport,created_date,-1,-1;last_edited_user "last_edited_user" true true true 255 Text 0 0,First,#,L:/ESRI_Projects/Roading/Footpaths/Monowai footpath condition/Monowai footpath condition.gdb/FootpathInspectionExport,last_edited_user,0,254;last_edited_date "last_edited_date" true true true 8 Date 0 1,First,#,L:/ESRI_Projects/Roading/Footpaths/Monowai footpath condition/Monowai footpath condition.gdb/FootpathInspectionExport,last_edited_date,-1,-1;condition "Condition" true true false 8 Double 0 0,First,#,L:/ESRI_Projects/Roading/Footpaths/Monowai footpath condition/Monowai footpath condition.gdb/FootpathInspectionExport,condition,-1,-1;Shape_Length "Shape_Length" false true true 8 Double 0 0,First,#,L:/ESRI_Projects/Roading/Footpaths/Monowai footpath condition/Monowai footpath condition.gdb/FootpathInspectionExport,Shape_Length,-1,-1',
            match_option=Match_Option,
            search_radius=(
                Search_Radius.__str__().format(**locals(), **globals())
                if isinstance(Search_Radius, str)
                else Search_Radius
            ),
        )
        # Process: Export Features (Export Features) (conversion)
        FootpathConditionSorted = f"{arcpy.env.workspace}/FootpathConditionSorted"
        arcpy.conversion.ExportFeatures(
            in_features=FootpathRouteEventCondition,
            out_features=FootpathConditionSorted,
            field_mapping='Join_Count "Join_Count" true true false 0 Long 0 0,First,#,memory/FootpathRouteEventCondition,Join_Count,-1,-1;TARGET_FID "TARGET_FID" true true false 0 Long 0 0,First,#,memory/FootpathRouteEventCondition,TARGET_FID,-1,-1;RID "RID" true true false 0 Long 0 0,First,#,memory/FootpathRouteEventCondition,RID,-1,-1;MEAS "MEAS" true true false 0 Double 0 0,First,#,memory/FootpathRouteEventCondition,MEAS,-1,-1;InPoly_ID "InPoly_ID" true true false 4 Long 0 0,First,#,memory/FootpathRouteEventCondition,InPoly_ID,-1,-1;InPoly_FID "InPoly_FID" true true false 4 Long 0 0,First,#,memory/FootpathRouteEventCondition,InPoly_FID,-1,-1;InLine_ID "InLine_ID" true true false 4 Long 0 0,First,#,memory/FootpathRouteEventCondition,InLine_ID,-1,-1;InLine_FID "InLine_FID" true true false 4 Long 0 0,First,#,memory/FootpathRouteEventCondition,InLine_FID,-1,-1;MIN_WIDTH "MIN_WIDTH" true true false 8 Double 0 0,First,#,memory/FootpathRouteEventCondition,MIN_WIDTH,-1,-1;MAX_WIDTH "MAX_WIDTH" true true false 8 Double 0 0,First,#,memory/FootpathRouteEventCondition,MAX_WIDTH,-1,-1;AVG_WIDTH "AVG_WIDTH" true true false 8 Double 0 0,First,#,memory/FootpathRouteEventCondition,AVG_WIDTH,-1,-1;COLLAPSED "COLLAPSED" true true false 4 Long 0 0,First,#,memory/FootpathRouteEventCondition,COLLAPSED,-1,-1;Shape_Length "Shape_Length" true true true 8 Double 0 0,First,#,memory/FootpathRouteEventCondition,Shape_Length_1,-1,-1;From_measure "From_measure" true true false 4 Float 0 0,First,#,memory/FootpathRouteEventCondition,From_measure,-1,-1;To_measure "To_measure" true true false 4 Float 0 0,First,#,memory/FootpathRouteEventCondition,To_measure,-1,-1;UID "UID" true true false 4 Long 0 0,First,#,memory/FootpathRouteEventCondition,UID,-1,-1;ORIG_FID "ORIG_FID" true true false 0 Short 0 0,First,#,memory/FootpathRouteEventCondition,ORIG_FID,-1,-1;esrignss_avg_h_rms "Average horizontal accuracy (m)" true true false 0 Double 0 0,First,#,memory/FootpathRouteEventCondition,esrignss_avg_h_rms,-1,-1;globalid "globalid" false false true 38 GlobalID 0 0,First,#,memory/FootpathRouteEventCondition,globalid,-1,-1;SHAPE__Length "SHAPE__Length" false true true 0 Double 0 0,First,#,memory/FootpathRouteEventCondition,SHAPE__Length,-1,-1;created_user "created_user" false true true 255 Text 0 0,First,#,memory/FootpathRouteEventCondition,created_user,0,254;created_date "created_date" false true true 29 Date 0 1,First,#,memory/FootpathRouteEventCondition,created_date,-1,-1;last_edited_user "last_edited_user" false true true 255 Text 0 0,First,#,memory/FootpathRouteEventCondition,last_edited_user,0,254;last_edited_date "last_edited_date" false true true 29 Date 0 1,First,#,memory/FootpathRouteEventCondition,last_edited_date,-1,-1;condition "Condition" true true false 0 Double 0 0,First,#,memory/FootpathRouteEventCondition,condition,-1,-1',
            sort_field=Sort_Field,
        )
        # Process: Export and delete NULL condition records
        NullConditionLayer = "FootpathConditionSortedNullCleanup"
        NullConditionOutput = f"{arcpy.env.workspace}/FootpathConditionNull"
        condition_field = "condition"
        field_names = [field.name for field in arcpy.ListFields(FootpathConditionSorted)]
        actual_field = next(
            (name for name in field_names if name.lower() == condition_field.lower()),
            None,
        )
        if actual_field:
            where_clause = (
                f"{arcpy.AddFieldDelimiters(FootpathConditionSorted, actual_field)} "
                "IS NULL"
            )
            arcpy.management.MakeFeatureLayer(FootpathConditionSorted, NullConditionLayer)
            arcpy.management.SelectLayerByAttribute(
                NullConditionLayer, "NEW_SELECTION", where_clause
            )
            null_count = int(arcpy.management.GetCount(NullConditionLayer)[0])
            if null_count > 0:
                arcpy.conversion.ExportFeatures(
                    in_features=NullConditionLayer,
                    out_features=NullConditionOutput,
                )
                arcpy.AddMessage(
                    f"Exported {null_count} NULL condition records to "
                    f"{NullConditionOutput}."
                )
                arcpy.management.DeleteRows(NullConditionLayer)
                arcpy.AddMessage(
                    f"Deleted {null_count} records from {FootpathConditionSorted} "
                    f"where {actual_field} is NULL."
                )
            else:
                arcpy.AddMessage(
                    f"No NULL values found in {actual_field} for "
                    f"{FootpathConditionSorted}."
                )
            arcpy.management.Delete(NullConditionLayer)
        else:
            arcpy.AddWarning(
                f"Field '{condition_field}' was not found in "
                f"{FootpathConditionSorted}; NULL condition cleanup skipped."
            )
        aprx = arcpy.mp.ArcGISProject("CURRENT")
        active_map = aprx.activeMap
        if active_map is not None:
            sorted_layer = next(
                (
                    layer
                    for layer in active_map.listLayers()
                    if layer.name == "FootpathConditionSorted"
                ),
                None,
            )
            if sorted_layer is None:
                active_map.addDataFromPath(FootpathConditionSorted)
            apply_condition_symbology("FootpathConditionSorted")
        else:
            arcpy.AddWarning(
                "No active map was found; FootpathConditionSorted was not added "
                "or symbolized."
            )
    if __name__ == "__main__":
        RouteCreation(*argv[1:])

    arcpy.AddMessage("Route creation process finished.")
