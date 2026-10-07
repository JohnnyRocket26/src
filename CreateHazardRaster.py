import os
import arcpy
import numpy as np
from arcpy.sa import *

# 1. Check out the Spatial Analyst extension
arcpy.CheckOutExtension("Spatial")

# 2. Read parameters: depth*velocity raster, depth raster, output raster
raster_path1 = arcpy.GetParameterAsText(0)
raster_path2 = arcpy.GetParameterAsText(1)
output_name = arcpy.GetParameterAsText(2)

# Output goes into the current project's default geodatabase
default_gdb = arcpy.mp.ArcGISProject("CURRENT").defaultGeodatabase
output_path = os.path.join(default_gdb, output_name)
# 3. Create Raster Objects
# Cast the paths as Raster objects for map algebra to work
dv = Raster(raster_path1)
d = Raster(raster_path2)

def get_flood_risk_category(dv: float, depth: float) -> int:
    """
    Determines the flood hazard category (H1-H6) based on depth*velocity and depth.
    
    Parameters:
    dv (float): Depth multiplied by Velocity (m^2/s)
    depth (float): Depth of the water (m)
    
    Returns:
    str: Risk category from 'H1' to 'H6'
    """
# 1. Calculate velocity safely using np.where to avoid division by zero
    velocity = Con(depth > 0, dv / depth, 0.0)

# 2. Define your classification zones using masks (boolean arrays)
    # Check H1 Boundaries
    h1 = Con((depth <= 0.3) & (velocity <= 2.0) & (dv <= 0.3), 1, 0)

    # Check H2 Boundaries
    h2 = Con((depth <= 0.5) & (velocity <= 2.0) & (dv <= 0.6), 1, 0)

    # Check H3 Boundaries
    h3 = Con((depth <= 1.2) & (velocity <= 2.0) & (dv <= 0.6), 1, 0)

    # Check H4 Boundaries
    h4 = Con((depth <= 2.0) & (velocity <= 2.0) & (dv <= 1.0), 1, 0)

    # Check H5 Boundaries
    h5 = Con((depth <= 4.0) & (velocity <= 4.0) & (dv <= 4.0), 1, 0)


# 3. Create an empty array to hold the text categories (e.g., matching the raster shape)
    risk_raster = Con(h1, 1,
                    Con(h2, 2,
                      Con(h3, 3,
                        Con(h4, 4,
                          Con(h5, 5, 6))))) # Defaults to 6 (H6) if it fits no other criteria
    
    return risk_raster

hazard_raster = get_flood_risk_category(dv, d)

# 5. Save the result to a new file
hazard_raster.save(output_path)


