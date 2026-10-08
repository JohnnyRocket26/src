import arcpy

# Set environment settings
arcpy.env.workspace = r"C:\Data\MyProject.gdb"
arcpy.env.overwriteOutput = True

# Define inputs and outputs
input_table = r"C:\Data\addresses.xlsx"  # Or .csv / .gdb table
# Using ArcGIS World Geocoding Service or a local locator
locator = "GC_World"  # Replace with your locator path or service
output_folder = r"C:\Data\Outputs"
output_name = "Geocoded_Addresses"

# Define field mappings based on your spreadsheet columns
# Format: "Locator_Field Spreadsheet_Field VISIBLE NONE; ..."
field_mapping = (
    "Address or Place 'Street Address' VISIBLE NONE;"
    "City City VISIBLE NONE;"
    "State State VISIBLE NONE;"
    "ZIP ZIP_Code VISIBLE NONE"
)

try:
    print("Starting geocoding process...")
    arcpy.geocoding.GeocodeFile(
        in_table=input_table,
        in_locator=locator,
        address_field_mapping=field_mapping,
        output_type="FEATURE_CLASS",
        output_folder=output_folder,
        output_name=output_name,
    )
    print(f"Geocoding complete! Output saved as {output_name}")

except Exception as e:
    print(f"An error occurred: {e}")
