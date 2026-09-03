# %%

# This #%% command let you run the python code in the cell (like jupyter notebook) when you are using VS Code (or other IDEs that support it).

import os
import dask
import pandas as pd
import numpy as np
import xarray as xr  # one of the most popular libraries for working with gridded data
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
# import rasterio
import rioxarray  # registers the .rio accessor used below

# %% CONFIG ================================
# var_name = "pr"
var_name = "etr"
data_dir = r"C:\Users\flipl\OneDrive - Cal Poly\NR3320\data\gridmet"
out_dir = r"C:\Users\flipl\OneDrive - Cal Poly\NR3320_share\2026F\1_watershed_water_balance_lab\gridmet_data"
water_years = [2023, 2024, 2025]
# ================================

var_dict = {
    "pr": "precipitation_amount",
    "etr": "potential_evapotranspiration",
}

# %% Initial configuration ================================

# Make output directory
os.makedirs(out_dir, exist_ok=True)

# Make a list of the calendar years that contain the water years
# Water year YYYY = Oct 1 of (YYYY-1) through Sep 30 of YYYY
calendar_years = list(range(min(water_years) - 1, max(water_years)+1))  # 2022-2025

# %% Get the list of gridmet files
nc_files = [
    os.path.join(data_dir, f"{var_name}_{year}.nc") for year in calendar_years
]
missing = [path for path in nc_files if not os.path.exists(path)]
if missing:
    raise FileNotFoundError("Missing GridMET files:\n" + "\n".join(missing))

nc_files

# %% Data curation ================================

# Stack daily precipitation or potential evapotranspiration across years. 
# Chunk by day so the 4 x ~2 GB files are not all loaded into memory at once. 
# Dask is used to handle the large dataset works together with xarray to process the data.

ds = xr.open_mfdataset(
    nc_files,
    combine="by_coords",
    chunks={"day": 30},
    drop_variables=["crs"],
)
da = ds[var_dict[var_name]]
da

# %% Assign water year on the time ("day") dimension
month = da["day"].dt.month
year = da["day"].dt.year
water_year = xr.where(month >= 10, year + 1, year)
da = da.assign_coords(water_year=("day", water_year.values))

# Keep only the requested water years (WY 2023-2025)
da_filt = da.sel(day=da["water_year"].isin(water_years))
da_filt

# %% Summarize the data by water year
# Total annual precipitation (mm) or total annual potential evapotranspiration (mm) for each water year
da_sum = da_filt.groupby("water_year").sum("day")
da_sum = da_sum.rio.write_crs("EPSG:4326") # Need to set CRS (coordinate reference system) to make it GIS-aware
da_sum = da_sum.rio.set_spatial_dims(x_dim="lon", y_dim="lat")

# Mask where precipitation or potential evapotranspiration is 0 
da_sum = da_sum.where(da_sum > 0)

da_sum

# %% Visual check: water year 2023 total precipitation or total potential evapotranspiration
da_sum.sel(water_year=2023).plot()

# %% Finalize data curation ================================

# Write one GeoTIFF per water year for ArcGIS
tif_paths = []
for wy in water_years:
    # Select the data for the water year and drop the water year dimension
    da_sum_wy = da_sum.sel(water_year=wy).drop_vars("water_year", errors="ignore")
    tif_path = os.path.join(out_dir, f"{var_name}_wy{wy}_sum.tif")

    # Write the data to a GeoTIFF file
    da_sum_wy.rio.to_raster(
        tif_path,
        driver="GTiff",
        compress="LZW",
        dtype="float32",
    )
    # Add the path to the list of paths
    tif_paths.append(tif_path)
    print(tif_path)

# List of paths to the GeoTIFF files
tif_paths

# %%
# Close the dataset to free up memory
ds.close()

