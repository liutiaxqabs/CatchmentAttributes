import cv2
import netCDF4
import numpy as np
import pandas as pd
import xarray

from utils import *

"""
Calculate catchment aggregated soil characteristics.

The directory should be structured as follows:
├── soil.py
├── shapefiles
|   ├── basin_0000.shp
|   ├── basin_0001.shp
├── data
|   ├── soil_souce_data
|   |   ├── tif
|   |   ├── netcdf
|   |   ├── binary

### Data sources ###

1. Dai, Y., Q. Xin, N. Wei, Y. Zhang, W. Shangguan, H. Yuan, S. Zhang, S. Liu, and X. Lu (2019b), 
A global high-resolution dataset of soil hydraulic and thermal properties for land surface modeling, 
J. Adv. Model. Earth System, accepted.

Download link:
http://globalchange.bnu.edu.cn/research/soil5.jsp (binary)
We used the column "Data for SoilGrids" for producing the BACC dataset

2. Shangguan, W., Y. Dai, B. Liu, A. Zhu, Q. Duan, L. Wu, D. Ji, A. Ye, H. Yuan, Q. Zhang, D. Chen, M. Chen, 
J. Chu, Y. Dou, J. Guo, H. Li, J. Li, L. Liang, X. Liang, H. Liu, S. Liu, C. Miao, and Y. Zhang (2013), 
A China Dataset of Soil Properties for Land Surface Modeling, Journal of Advances in Modeling Earth Systems, 
5: 212-224.

Download link:
http://globalchange.bnu.edu.cn/research/soil2 (netCDF)

3. Hengl T, Mendes de Jesus J, Heuvelink GBM, Ruiperez Gonzalez M, Kilibarda M, Blagotić A, et al. (2017) 
SoilGrids250m: Global gridded soil information based on machine learning. PLoS ONE 12(2): e0169748. 
doi:10.1371/journal.pone.0169748

Download link:
https://files.isric.org/soilgrids/former/2017-03-10/data/ 

List of descriptions:
https://github.com/ISRICWorldSoil/SoilGrids250m/blob/master/grids/models/META_GEOTIFF_1B.csv


### Instruction ###

The soil data comes from different data sources. The original data of SoilGrids is in GeoTIFF format, 
while other data sources first need to be converted to GeoTIFF and then zonal stats are performed to obtain 
the basin average.

When you have prepared the relevant data, this code can run normally "without modification". However, since there are 
so many soil types data, users may want to deal with data types that are not included in the source 
data set. Therefore, the following steps introduces a general method of processing soil source data into a watershed 
area average using this python script:
(1) Download the attribute source files that you need, put them in the corresponding folders according to their types; 
(2) For nc file, you will need to find the variable name using function nc_var_description for extracting array from nc 
and then converting the array to tif, specify the variable name in L179, you may need to create a mapping dictionary 
from file names to variable names if you are processing multiple variables simultaneously;
(3) You will need to specify the valid value ranges for the converted tif files in L196, similarly, a file_name -> value 
range mapping might be needed if you are processing multiple variable simultaneously.

"""


def read_nc_data(ncfile: str):
    """
    Read .nc data and return two dictionaries. The first dictionary contains variable names and variables,
    and the second dictionary contains descriptions of the variable names

    Parameters
    ----------
    ncfile: The path of the .nc file

    Returns
    -------
    (dict1, dict2)

    dict1: {variable name: variable}
    dict2: {variable name: description}
    """
    try:
        with netCDF4.Dataset(ncfile) as file:
            file.set_auto_mask(False)
            variables = {x: file[x][()] for x in file.variables}
        with xarray.open_dataset(ncfile) as file:
            longnames = {}
            for x in file.variables:
                if "longname" in file[x].attrs:
                    longnames[x] = file[x].longname
                else:
                    longnames[x] = file[x].long_name
            units = {}
            for x in file.variables:
                if "units" in file[x].attrs:
                    units[x] = file[x].units
        return variables, longnames, units

    except IOError:
        print(f"File corrupted: {ncfile}")


def nc_var_description(ncfile: str):
    return read_nc_data(ncfile)[1]


def tif_from_array(mag_grid: np.array, output_file: str):
    """
    For data from:
    Dai, Y., Q. Xin, N. Wei, Y. Zhang, W. Shangguan, H. Yuan, S. Zhang, S. Liu, and X. Lu (2019b),
    A global high-resolution dataset of soil hydraulic and thermal properties for land surface modeling,
    J. Adv. Model. Earth System, accepted.
    """
    lats = np.arange(-90, 90, 0.08333333333333333)
    lons = np.arange(-180, 180, 0.08333333333333333)
    xres = lons[1] - lons[0]
    yres = lats[1] - lats[0]
    ysize = len(lats)
    xsize = len(lons)
    ulx = -180
    uly = -90
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(output_file, xsize, ysize, 1, gdal.GDT_Float32)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    gt = [ulx, xres, 0, uly, 0, yres]
    ds.SetGeoTransform(gt)
    outband = ds.GetRasterBand(1)
    outband.SetStatistics(
        np.min(mag_grid), np.max(mag_grid), np.average(mag_grid), np.std(mag_grid)
    )
    outband.WriteArray(mag_grid)
    ds = None


def tif_from_nc(ncfile: str, variable_key: str, output_file: str):
    """
    Convert a variable of the .nc file to a tif file.

    netCDF source data:
    Shangguan, W., Y. Dai, B. Liu, A. Zhu, Q. Duan, L. Wu, D. Ji, A. Ye, H. Yuan, Q. Zhang, D. Chen, M. Chen,
    J. Chu, Y. Dou, J. Guo, H. Li, J. Li, L. Liang, X. Liang, H. Liu, S. Liu, C. Miao, and Y. Zhang (2013),
    A China Dataset of Soil Properties for Land Surface Modeling, Journal of Advances in Modeling Earth Systems,
    5: 212-224.

    Parameters
    ----------
    ncfile
        The path of the .nc file
    variable_key
        The variable name of the .nc file to be written to the tif file
    output_file
        path of the output tif file
    """

    variables = read_nc_data(ncfile)[0]
    desc = read_nc_data(ncfile)[1]
    target_variable = variables[variable_key]
    if len(target_variable.shape) == 3:
        target_variable = target_variable[0]  # Only count the first layer
    mag_grid = np.float64(target_variable)
    lats = np.arange(18.004168, 53.995834, 0.008331404166666667)
    lons = np.arange(73.004166, 135.99583, 0.0083333)

    xres = lons[1] - lons[0]
    yres = lats[1] - lats[0]
    ysize = len(lats)
    xsize = len(lons)
    ulx = 73.004166
    uly = 18.004168
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(output_file, xsize, ysize, 1, gdal.GDT_Float32)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    gt = [ulx, xres, 0, uly, 0, yres]
    ds.SetGeoTransform(gt)
    outband = ds.GetRasterBand(1)
    outband.SetStatistics(
        np.min(mag_grid), np.max(mag_grid), np.average(mag_grid), np.std(mag_grid)
    )
    outband.WriteArray(mag_grid)
    ds = None


def binary2tif(file, out_path):
    """
    Parameters
    ----------
    file
        /path/to/binary
    out_path
        out/tif/path

    Returns
    -------
    None
    """

    data = np.fromfile(file, dtype=np.float64).reshape((21600, 43200))
    data[data == data.min()] = -9999
    tif_from_array(
        cv2.flip(np.rot90(cv2.resize(data, (43200 // 10, 21600 // 10)), 2), 1), out_path
    )


def all_soil_depth_mean_weight_in_soilgrids250(attr_df: pd.DataFrame):
    """
    Read sajd/silt/clay weight in all soil depths for a basin and get the average value over all depth intervals

    Details could be seen in this paper: 10.1371/journal.pone.0169748

    Parameters
    ----------
    attr_df
        attributes of basins

    Returns
    -------
    pd.Dataframe
        Soil attr value average over all layers in a basin
    """
    all_cols = attr_df.columns.values
    cols = [col.split("_")[0] for col in all_cols if "sl1" in col]
    soil_depths = np.array([0, 5, 15, 30, 60, 100, 200])
    heights = soil_depths[1:] - soil_depths[:-1]
    for i in range(len(cols)):
        attr_ = attr_df.filter(regex=cols[i])
        all_numbers = np.zeros(attr_.shape)
        mean_value = np.zeros(attr_.shape[0])
        # to guarantee the sequence is correct, we use a loop rather than apply function
        for j in range(1, 8):
            all_numbers[:, j - 1] = attr_.filter(regex="sl" + str(j)).values.flatten()
        for k in range(len(mean_value)):
            mean_value[k] = (
                np.sum(heights * (all_numbers[k, :-1] + all_numbers[k, 1:]) / 2) / 200
            )
        attr_df[cols[i]] = mean_value
    return attr_df
