"""Geocode an address table and save the result to a geodatabase.

Script tool parameters (in order):
    0  Input Table            (Table View / File)         Required, Input
    1  Locator                (String or Address Locator) Required, Input, default NZ_Addresses_Locator.loc
    2  Address Field          (Field)                     Optional, Input; obtained from parameter 0; auto-detected if blank
    3  City Field             (Field)                     Optional, Input; obtained from parameter 0; auto-detected if blank
    4  State Field            (Field)                     Optional, Input; obtained from parameter 0; auto-detected if blank
    5  ZIP Field              (Field)                     Optional, Input; obtained from parameter 0; auto-detected if blank
    6  Country                (String, multivalue)        Optional, Input; e.g. NZL
    7  Output Geodatabase     (Workspace)                 Optional, Input; defaults to the project's default geodatabase
    8  Output Name            (String)                    Required, Input, default "Geocoded_Addresses"
    9  Output Feature Class   (Feature Class)             Derived, Output

Parameters 2-5 should use a String field filter and be "Obtained from" the Input Table.
Geocode Addresses is used (not Geocode File) because Geocode File does not support the
ArcGIS World Geocoding Service and requires an Enterprise portal locator.
"""
import os

import arcpy

DEFAULT_LOCATOR = r"l:\ESRI_Projects\ClimateChange\Projects\SR_67715_OCCRA_Sea_Level_Rise\NZ_Addresses_Locator.loc"
DEFAULT_OUTPUT_NAME = "Geocoded_Addresses"
# Locator field name and the table field names auto-detected for it when the picker is left blank
LOCATOR_FIELDS = {
    2: ("Address or Place", ("address", "fulladdress", "streetaddress", "property", "propertyaddress", "location", "site", "siteaddress")),
    3: ("City", ("city", "town", "suburb", "locality")),
    4: ("State", ("state", "province", "region")),
    5: ("ZIP", ("zip", "zipcode", "postcode", "postalcode", "postal")),
}


def detect_field(table_fields: dict[str, str], aliases: tuple[str, ...]) -> str:
    """Return the table field whose normalized name matches the first alias that exists."""
    normalized = {name.lower().replace("_", "").replace(" ", ""): name for name in table_fields.values()}
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    return ""


def build_field_mapping(table: str) -> str:
    """Build the GeocodeAddresses mapping string from the picked fields, auto-detecting blanks from the table."""
    table_fields = {
        f.name.lower(): f.name for f in arcpy.ListFields(table) if f.type == "String"
    }
    parts = []
    for index, (locator_field, aliases) in LOCATOR_FIELDS.items():
        field = arcpy.GetParameterAsText(index)
        if field:
            if field.lower() not in table_fields:
                raise ValueError(f"Field '{field}' was not found in {table}")
        else:
            field = detect_field(table_fields, aliases)
            if field:
                arcpy.AddMessage(f"Auto-detected '{field}' for {locator_field}")
        if field:
            parts.append(f"'{locator_field}' '{field}' VISIBLE NONE")
    if not parts:
        raise ValueError("No address field was selected or could be detected in the input table.")
    return ";".join(parts)


def get_default_geodatabase() -> str:
    """Return the current project's default geodatabase, falling back to the workspace/scratch GDB."""
    try:
        gdb = arcpy.mp.ArcGISProject("CURRENT").defaultGeodatabase
        if gdb:
            return gdb
    except OSError:
        pass  # Not running inside an ArcGIS Pro session

    workspace = arcpy.env.workspace
    if workspace and workspace.lower().endswith(".gdb"):
        return workspace
    return arcpy.env.scratchGDB


def main() -> None:
    input_table = arcpy.GetParameterAsText(0)
    locator = arcpy.GetParameterAsText(1) or DEFAULT_LOCATOR
    country = arcpy.GetParameterAsText(6)
    output_gdb = arcpy.GetParameterAsText(7) or get_default_geodatabase()
    output_name = arcpy.GetParameterAsText(8) or DEFAULT_OUTPUT_NAME

    if not input_table:
        raise ValueError("An input table is required.")
    if not arcpy.Exists(input_table):
        raise ValueError(f"Input table does not exist: {input_table}")
    field_mapping = build_field_mapping(input_table)
    if not output_gdb.lower().endswith(".gdb") or not arcpy.Exists(output_gdb):
        raise ValueError(f"Output location must be an existing file geodatabase: {output_gdb}")

    output_name = arcpy.ValidateTableName(output_name, output_gdb)

    arcpy.env.workspace = output_gdb
    arcpy.env.overwriteOutput = True

    output_fc = os.path.join(output_gdb, output_name)

    arcpy.AddMessage(f"Geocoding {input_table} with {locator}...")
    arcpy.geocoding.GeocodeAddresses(
        in_table=input_table,
        address_locator=locator,
        in_address_fields=field_mapping,
        out_feature_class=output_fc,
        country=country or None,
    )

    if not arcpy.Exists(output_fc):
        raise RuntimeError(f"Geocoding finished but output was not found: {output_fc}")

    arcpy.SetParameterAsText(9, output_fc)
    arcpy.AddMessage(f"Geocoding complete. Output saved to {output_fc}")


if __name__ == "__main__":
    try:
        main()
    except arcpy.ExecuteError:
        arcpy.AddError(arcpy.GetMessages(2))
        raise
    except Exception as exc:
        arcpy.AddError(str(exc))
        raise
