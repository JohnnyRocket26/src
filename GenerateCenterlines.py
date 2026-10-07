# -*- coding: utf-8 -*-

import arcpy
import math
import os
from sys import argv

def run_generateCenterlines():
    """Core logic to generate centerlines."""
    arcpy.AddMessage("Executing centerline generation script logic...")

    # Abstract: Generates footpath centerlines from dissolved footpath polygons by collapsing hydro polygons, correcting line endpoints with adjacent polygon corner midpoints, assigning route measures and unique identifiers, removing segments shorter than two units, and adding the completed feature class to the active ArcGIS Pro map.
    # Process summary:
    # 1. Resolve the footpath export input and use its geodatabase for outputs. 
    # 2. Collapse hydro polygons to create initial hydro centerlines.
    # 3. Create a bounding box around the dissolved footpath polygons.
    # 4. Identify suitable corner legs, create their midpoints, and snap the
    #    centerline endpoints to those midpoints.
    # 5. Populate the centerline From_measure, To_measure, and UID fields.
    # 6. Delete any records in the centerlines feature class with Shape_Length less than 2.
    # 7. Add the completed Centerlines feature class to the active map.
    # 8. Delete any temporary in-memory layers.
    # For inline variable substitution, parameters passed as a String are evaluated using locals(), globals() and isinstance(). To override, substitute values directly.
    def get_short_leg_geometry(point_1, point_2, point_3, spatial_reference):
        """Return the shorter leg when the interior angle is approximately 90 degrees."""
        try:
            distance_12 = math.sqrt(
                (point_2.X - point_1.X) ** 2 + (point_2.Y - point_1.Y) ** 2
            )
            distance_23 = math.sqrt(
                (point_3.X - point_2.X) ** 2 + (point_3.Y - point_2.Y) ** 2
            )
            distance_13 = math.sqrt(
                (point_3.X - point_1.X) ** 2 + (point_3.Y - point_1.Y) ** 2
            )
            angle = math.acos(
                (distance_12**2 + distance_23**2 - distance_13**2)
                / (2 * distance_12 * distance_23)
            )
            angle_degrees = math.degrees(angle)
            if 70 <= angle_degrees <= 100:
                if distance_12 < distance_23:
                    points = arcpy.Array([point_1, point_2])
                else:
                    points = arcpy.Array([point_2, point_3])
                return arcpy.Polyline(points, spatial_reference)
        except (ValueError, ZeroDivisionError):
            pass
        return None
    def CorrectCenterlines(
        line_feature, polygon_feature, bounding_box, midpoints, centerlines
    ):
        """Create corner midpoints and snap the centerlines to them."""
        scratch_workspace = "memory"
        spatial_reference = arcpy.Describe(polygon_feature).spatialReference
        arcpy.env.outputCoordinateSystem = spatial_reference
        arcpy.env.extent = arcpy.Describe(bounding_box).extent
        arcpy.AddMessage("Loading data into memory...")
        polygon_layer = arcpy.management.MakeFeatureLayer(
            polygon_feature, f"{scratch_workspace}/polygon_layer"
        )
        arcpy.management.SelectLayerByLocation(polygon_layer, "INTERSECT", bounding_box)
        polygon_geometries = [
            [row[0], row[1]]
            for row in arcpy.da.SearchCursor(polygon_layer, ["SHAPE@", "OID@"])
        ]
        line_layer = arcpy.management.MakeFeatureLayer(
            line_feature, f"{scratch_workspace}/line_layer"
        )
        arcpy.management.SelectLayerByLocation(line_layer, "INTERSECT", bounding_box)
        line_geometries = [row[0] for row in arcpy.da.SearchCursor(line_layer, ["SHAPE@"])]
        output_workspace = os.path.dirname(midpoints)
        midpoint_name = os.path.basename(midpoints)
        if not arcpy.Exists(output_workspace):
            raise RuntimeError(f"Output workspace does not exist: {output_workspace}")
        if arcpy.Exists(midpoints):
            arcpy.management.Delete(midpoints)
        if arcpy.Exists(centerlines):
            arcpy.management.Delete(centerlines)
        arcpy.management.CreateFeatureclass(
            output_workspace, midpoint_name, "POINT", spatial_reference=spatial_reference
        )
        midpoint_count = 0
        arcpy.AddMessage("Processing midpoints...")
        with arcpy.da.InsertCursor(midpoints, ["SHAPE@"]) as insert_cursor:
            for polygon_geometry, polygon_id in polygon_geometries:
                for part in polygon_geometry:
                    for point_index in range(len(part) - 1):
                        point_2 = part[point_index]
                        point_1 = (
                            part[point_index - 1]
                            if point_index > 0
                            else part[len(part) - 2]
                        )
                        point_3 = part[point_index + 1]
                        short_leg = get_short_leg_geometry(
                            point_1, point_2, point_3, spatial_reference
                        )
                        if short_leg and any(
                            not short_leg.disjoint(line_geometry)
                            for line_geometry in line_geometries
                        ):
                            midpoint = arcpy.PointGeometry(
                                short_leg.centroid, spatial_reference
                            )
                            midpoint_check_area = midpoint.buffer(0.05)
                            is_adjacent = any(
                                polygon_id != other_id
                                and not midpoint_check_area.disjoint(other_geometry)
                                for other_geometry, other_id in polygon_geometries
                            )
                            if not is_adjacent:
                                insert_cursor.insertRow([midpoint])
                                midpoint_count += 1
        arcpy.management.DeleteIdentical(midpoints, ["Shape"])
        arcpy.management.CopyFeatures(line_layer, centerlines)
        arcpy.edit.Snap(centerlines, [[midpoints, "END", "3 Meters"]])
        arcpy.management.Delete(polygon_layer)
        arcpy.management.Delete(line_layer)
        arcpy.AddMessage(f"Created {midpoint_count} midpoints.")
        arcpy.AddMessage("Centerlines snapped successfully.")
    def add_centerlines_to_current_map(centerlines_path):
        """Add the completed centerlines feature class to the active ArcGIS Pro map."""
        project = arcpy.mp.ArcGISProject("CURRENT")
        current_map = project.activeMap
        if current_map is None:
            arcpy.AddWarning(
                "No active map is available; centerlines were not added to a map."
            )
            return
        current_map.addDataFromPath(centerlines_path)
        arcpy.AddMessage(f"Added centerlines to the current map: {current_map.name}")
    def CreateCenterlines(
        Footpath_dissolve=r"{arcpy.env.workspace}\FootpathDissolved",
    ):  # Step 1 Create centerlines
        # To allow overwriting outputs change overwriteOutput option to True.
        arcpy.env.overwriteOutput = True
        footpath_dissolve_value = (
            Footpath_dissolve.__str__().format(**locals(), **globals())
            if isinstance(Footpath_dissolve, str)
            else Footpath_dissolve
        )
        output_workspace = arcpy.Describe(footpath_dissolve_value).path
        geometry_type = "RECTANGLE_BY_AREA"
        group_option = "ALL"
        centerlines_path = output_workspace + "\\Centerlines"
        # Process: Collapse Hydro Polygon (Collapse Hydro Polygon) (cartography)
        hydro_centerlines_path = output_workspace + "\\chpHydroLine"
        output_polygon_feature_class = ""
        arcpy.cartography.CollapseHydroPolygon(
            in_features=[footpath_dissolve_value],
            out_line_feature_class=hydro_centerlines_path,
            out_poly_feature_class=output_polygon_feature_class,
        )
        # Process: Minimum Bounding Geometry (Minimum Bounding Geometry) (management)
        bounding_box_path = output_workspace + "\\BoundingBox"
        arcpy.management.MinimumBoundingGeometry(
            in_features=footpath_dissolve_value,
            out_feature_class=bounding_box_path,
            geometry_type=geometry_type,
            group_option=group_option,
        )
        # Process: Correct centerlines (Step 1 Correct centerlines) (fp)
        midpoints_path = output_workspace + "\\Midpoints"
        CorrectCenterlines(
            hydro_centerlines_path,
            footpath_dissolve_value,
            bounding_box_path,
            midpoints_path,
            centerlines_path,
        )
        # Process: Calculate Field (Calculate Field) (management)
        arcpy.management.CalculateField(
            in_table=centerlines_path,
            field="From_measure",
            expression="'0'",
            field_type="FLOAT",
        )
        # Process: Calculate Field (2) (Calculate Field) (management)
        arcpy.management.CalculateField(
            in_table=centerlines_path,
            field="To_measure",
            expression="!Shape_Length!",
            field_type="FLOAT",
        )
        # Process: Calculate Field (3) (Calculate Field) (management)
        arcpy.management.CalculateField(
            in_table=centerlines_path,
            field="UID",
            expression="generate_numeric_id(!OBJECTID!, !Shape_Length!)",
            code_block="""import hashlib
    def generate_numeric_id(val1, val2, length=6):
        # Combine fields into a single string
        combined = f\"{val1}{val2}\"
        # Create the hash object
        hash_obj = hashlib.md5(combined.encode())
        # Convert hex to int and grab last 6 digits
        numeric_id = int(hash_obj.hexdigest(), 16) % (10**length)
        return numeric_id
    """,
            field_type="LONG",
        )[0]
        short_centerlines_layer = "CenterlinesShortSegments"
        arcpy.management.MakeFeatureLayer(
            centerlines_path,
            short_centerlines_layer,
            f"{arcpy.AddFieldDelimiters(centerlines_path, 'Shape_Length')} < 2",
        )
        short_segment_count = int(arcpy.management.GetCount(short_centerlines_layer)[0])
        if short_segment_count:
            arcpy.management.DeleteFeatures(short_centerlines_layer)
            arcpy.AddMessage(
                f"Deleted {short_segment_count} centerline records shorter than 2 units."
            )
        arcpy.management.Delete(short_centerlines_layer)
        intermediate_paths = [
            hydro_centerlines_path,
            output_workspace + "\\chpHydroLine_InLine_DecodeID",
            output_workspace + "\\chpHydroLine_InPoly_DecodeID",
        ]
        try:
            add_centerlines_to_current_map(centerlines_path)
        finally:
            for intermediate_path in intermediate_paths:
                if arcpy.Exists(intermediate_path):
                    arcpy.management.Delete(intermediate_path)
    if __name__ == "__main__":
        CreateCenterlines(*argv[1:])

    arcpy.AddMessage("Centerlines generation process finished.")