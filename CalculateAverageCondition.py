"""
Script documentation
Evaluates condition streaks grouped by RID and writes a boolean result to a target field.
"""
import arcpy
import pandas as pd

# Processing workflow:
# 1. Read the input feature class and validate the two buffer percentages.
# 2. Load route condition records into a pandas DataFrame.
# 3. Group the records by route identifier and sort them by route measure.
# 4. Identify contiguous sections where the condition value is greater than 3.
# 5. Expand and merge poor-condition sections using the selected buffer percentage.
# 6. Write repair-state values to the requested output field.
# 7. Repeat the calculation for the second buffer percentage and output field.
# 8. Return the updated feature class as the derived script-tool output.

def set_symbol_outline_no_color(symbol):
    symbol.outlineColor = {"RGB": [0, 0, 0, 0]}
    symbol.outlineWidth = 0

def apply_symbology(layer_name, field_name):
    """
    Apply unique value symbology:
    0=Medium Apple, 1=Mars Red
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
            "0": {"RGB": [141, 182, 0, 100]},
            "1": {"RGB": [165, 42, 42, 100]},
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

def script_tool(fc, buffer_percent, output_field="RepairState"):
    """Processes the input feature class and updates the target field.
    
    Args:
        fc: Feature class path
        buffer_percent: Percent of each bad-condition MEAS span used for side extension
            on both sides of the bad-condition span.
        output_field: Name of the output field to write results (default "RepairState")
    """
    arcpy.AddMessage("Reading data into pandas...")
    
    # 1. Dynamically get the Object ID field to map results back later
    try:
        desc = arcpy.Describe(fc)
    except Exception:
        try:
            desc = arcpy.Describe(str(fc).strip())
        except Exception as e:
            arcpy.AddError(f"Error describing feature class '{fc}': {e}")
            return fc
    oid_field = desc.OIDFieldName
    fields = [oid_field, "RID", "MEAS", "Condition"]
    # 2. Load into pandas
    try:
        data = [row for row in arcpy.da.SearchCursor(fc, fields)]
    except Exception as e:
        arcpy.AddError(f"Error reading feature class: {e}")
        return
        
    df = pd.DataFrame(data, columns=fields) # Use the dynamic list!
    
    # 3. Sort correctly
    df = df.sort_values(["RID", "MEAS"])
    results = []
    
    arcpy.AddMessage("Processing RID groups...")
    
    # 4. Process each RID group
    for rid, group in df.groupby('RID'):
        # Extract arrays for fast index-based processing
        conditions = group['Condition'].values
        meas = group['MEAS'].values
        n = len(conditions)
        
        # --- STEP A: Identify contiguous sections where Condition > 3 ---
        base_zones = []
        in_zone = False
        start_idx = 0
        
        for i in range(n):
            condition_value = conditions[i]
            if pd.notna(condition_value) and condition_value > 3:
                if not in_zone:
                    start_idx = i
                    in_zone = True
            else:
                if in_zone:
                    base_zones.append([start_idx, i - 1])
                    in_zone = False
        if in_zone:
            base_zones.append([start_idx, n - 1])
            
        # --- STEP B: Create buffers using percentage-based MEAS side extensions ---
        # Each entry: [buf_start, buf_end, base_start, base_end]
        # base_start/base_end track the original bad-condition span so we can
        # distinguish inner (bridged) records from outer buffer padding later.
        buffered_zones = []
        for z in base_zones:
            # Side extension in MEAS units = bad section length * percentage.
            section_meas_length = max(0.0, float(meas[z[1]] - meas[z[0]]))
            extension_meas = section_meas_length * (buffer_percent / 100.0)
            left_meas = meas[z[0]] - extension_meas
            right_meas = meas[z[1]] + extension_meas
            buf_start = int(meas.searchsorted(left_meas, side='left'))
            buf_end = int(meas.searchsorted(right_meas, side='right')) - 1
            buffered_zones.append([buf_start, buf_end, z[0], z[1]])
            
        # --- STEP C: Merge buffered zones if their indices overlap ---
        # Each entry: [buf_start, buf_end, inner_start, inner_end, count]
        # inner_start/inner_end span from the first to last base zone merged in.
        merged_buffered_zones = []
        for z in buffered_zones:
            if not merged_buffered_zones:
                merged_buffered_zones.append([z[0], z[1], z[2], z[3], 1])
            else:
                last_z = merged_buffered_zones[-1]
                # If current zone starts within or exactly contiguous to the last zone
                if z[0] <= last_z[1] + 1:
                    last_z[1] = max(last_z[1], z[1])
                    last_z[3] = max(last_z[3], z[3])  # extend inner_end
                    last_z[4] += 1
                else:
                    merged_buffered_zones.append([z[0], z[1], z[2], z[3], 1])
                    
        # --- STEP D: Combine zones if buffers are within MEAS = 0.6 ---
        # Same 5-element structure: [buf_start, buf_end, inner_start, inner_end, count]
        final_zones = []
        for z in merged_buffered_zones:
            if not final_zones:
                final_zones.append(list(z))
            else:
                last_z = final_zones[-1]
                # Check the physical distance (MEAS) between the end of the last buffer and start of the current
                meas_distance = meas[z[0]] - meas[last_z[1]]
                
                if meas_distance <= 0.6:
                    # Combine them into one contiguous block; extend inner_end and count
                    last_z[1] = max(last_z[1], z[1])
                    last_z[3] = max(last_z[3], z[3])
                    last_z[4] += z[4]
                else:
                    final_zones.append(list(z))
                    
        # --- STEP E: Assign output field values:
        # Standalone zones (count == 1): discard buffer and mark only the original
        #   bad-condition span (inner_start -> inner_end).
        # Merged zones   (count  > 1): mark from inner_start to inner_end (the
        #   bridged span between bad sections) and side extension around it.
        res = [0] * n
        for z in final_zones:
            buf_start, buf_end, inner_start, inner_end, count = z
            section_meas_length = max(0.0, float(meas[inner_end] - meas[inner_start]))
            extension_meas = section_meas_length * (buffer_percent / 100.0)
            left_meas = meas[inner_start] - extension_meas
            right_meas = meas[inner_end] + extension_meas
            mark_start = int(meas.searchsorted(left_meas, side='left'))
            mark_end = int(meas.searchsorted(right_meas, side='right')) - 1
            if count > 1:
                # Mark the inner span (first base zone start → last base zone end) as 1
                for i in range(mark_start, mark_end + 1):
                    res[i] = 1
            else:
                # Standalone zone: revert to the original bad-section extent only.
                for i in range(inner_start, inner_end + 1):
                    res[i] = 1
                
        # Store result for this RID
        group = group.copy()
        group[output_field] = res
        results.append(group)
    if not results:
        arcpy.AddWarning("No records were processed.")
        return fc
    # 5. Combine results and create an Update Dictionary {OID: Target_Field_Value}
    final_df = pd.concat(results)
    # Ensure values are integers (1/0) before creating the update dict
    update_dict = pd.Series(final_df[output_field].astype(int).values, index=final_df[oid_field]).to_dict()
    # 6. Ensure output field exists (Adding as SHORT: 1 = True, 0 = False)
    existing_fields = [f.name for f in arcpy.ListFields(fc)]
    if output_field not in existing_fields:
        arcpy.AddMessage(f"Adding '{output_field}' field to feature class...")
        arcpy.AddField_management(fc, output_field, "SHORT")
        
    # 7. Write the results back to the feature class
    arcpy.AddMessage(f"Writing {output_field} results to feature class...")
    with arcpy.da.UpdateCursor(fc, [oid_field, output_field]) as cursor:
        for row in cursor:
            oid = row[0]
            if oid in update_dict:
                # Write integer 1/0 directly
                row[1] = int(update_dict[oid])
                cursor.updateRow(row)
                
    return fc
    
if __name__ == "__main__":
    # Get the Input Feature Class from the Script Tool UI (Parameter 0)
    input_fc = arcpy.GetParameterAsText(0)
    
    try:
        buffer_a_input = arcpy.GetParameterAsText(1)
        buffer_a = float(buffer_a_input) if buffer_a_input else 50.0
        if buffer_a < 0:
            arcpy.AddWarning(f"buffer_A value {buffer_a} is negative. Using default of 50.0%.")
            buffer_a = 50.0
    except (ValueError, TypeError):
        arcpy.AddWarning("Invalid buffer_A value. Using default of 50.0%.")
        buffer_a = 50.0
    # Get buffer_B for Iter 2 (Parameter 3) as percentage with validation
    try:
        buffer_b_input = arcpy.GetParameterAsText(2)
        buffer_b = float(buffer_b_input) if buffer_b_input else 75.0
        if buffer_b < 0:
            arcpy.AddWarning(f"buffer_B value {buffer_b} is negative. Using default of 75.0%.")
            buffer_b = 75.0
    except (ValueError, TypeError):
        arcpy.AddWarning("Invalid buffer_B value. Using default of 75.0%.")
        buffer_b = 75.0
    # Execute script_tool twice with percentage-based side extensions.
    updated_fc = script_tool(
        input_fc,
        buffer_percent=buffer_a,
        output_field="RepairStateBa"
    )
    updated_fc = script_tool(
        updated_fc,
        buffer_percent=buffer_b,
        output_field="RepairStateBb"
    )
    
    # Output the result as a derived parameter (Parameter 3).
    arcpy.SetParameterAsText(3, updated_fc)
