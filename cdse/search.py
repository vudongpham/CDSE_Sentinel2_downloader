from pathlib import Path
from typing import Union, Pattern, Generator
from importlib.resources import files
import requests
import geopandas as gpd
from shapely.ops import transform
import json
import argparse
import re
from datetime import datetime
import os
import sys


# Checking input data
class argparseCondition():
    def dateRangeInput(self, value):
        def is_valid_date(date_str):
            """Check if the input string is a valid date in YYYYMMDD format."""
            try:
                datetime.strptime(date_str, "%Y%m%d")
                return True
            except ValueError:
                return False
        def format_date(a):
            return f'{a[0:4]}-{a[4:6]}-{a[6:8]}'
        
        pattern = r'^\d{8},\d{8}$'
        if not re.match(pattern, value):
            raise argparse.ArgumentTypeError(f"Invalid date range format: {value}. Expected format is YYYYMMDD,YYYYMMDD.")
        start_date, end_date = value.split(',')
        if not is_valid_date(start_date):
            raise argparse.ArgumentTypeError(f"Invalid date {start_date}")
        if not is_valid_date(end_date):
            raise argparse.ArgumentTypeError(f"Invalid date {end_date}")
        return format_date(start_date), format_date(end_date)
    
    def cloudCoverInput(self, value):
        try:
            # Split the string by the comma
            x_str, y_str = value.split(',')
            
            # Convert to integers
            x = int(x_str)
            y = int(y_str)
            
            # Check if both x and y are within the range [0, 100]
            if 0 <= x <= 100 and 0 <= y <= 100:
                return x, y
            else:
                raise ValueError("Cloud cover must be between 0 and 100.")
        
        except ValueError:
            raise argparse.ArgumentTypeError(f"Invalid input: {value}. Expected format is 'x,y' with x and y between 0 and 100.")


# # Convert vector file to WKT string
# def convert_polygon_to_WKT(aoi_path):
#     def drop_z(geometry):
#         if geometry.has_z:
#             return transform(lambda x, y, z=None: (x, y), geometry)
#         return geometry

#     # Read vector file
#     aoi = gpd.read_file(aoi_path)

#     # Reproject to WGS84
#     aoi = aoi.to_crs("EPSG:4326")

#     # Drop Z axis if any
#     aoi["geometry"] = aoi["geometry"].apply(drop_z)

#     # Disolve multipolygon
#     if len(aoi) > 1:
#         aoi = aoi.dissolve()

#     # Reduce the polygon geometries by 0.1 degree (WGS84) for the query
#     aoi = aoi.set_geometry(aoi.geometry.simplify(tolerance=0.1, preserve_topology=True))

#     # Output the reduced polygon to see what it look like
#     # aoi.to_file('test.gpkg', driver='GPKG')

#     # Get geometry_wkt
#     aoi['geometry_wkt'] = aoi['geometry'].apply(lambda geom: geom.wkt if geom else None)

#     # Return string
#     return aoi[['geometry_wkt']].values[0][0]


def convert_aoi_to_s2idlist(aoi_path):
    aoi = gpd.read_file(aoi_path)
    s2_path = files("cdse.aux_data").joinpath("sentinel2_grid.gpkg")
    s2_grid = gpd.read_file(s2_path)

    if aoi.crs != s2_grid.crs:
        aoi = aoi.to_crs(s2_grid.crs)

    intersection = gpd.overlay(aoi, s2_grid, how='intersection')

    s2_id_list = intersection['PRFID'].unique()
    s2_id_list = [x.strip() for x in s2_id_list]
    s2_id_list = [x[-5:] for x in s2_id_list]

    return s2_id_list


# Read list of Sentinel-2 id if .txt file is provided
def read_list_id(aoi_path):
    lines = []
    with open(aoi_path, 'r') as file:
        for line in file:
            line = line.strip()  
            if len(line) < 5 :
                pass
            elif len(line) == 5:
                lines.append(line)
            else:
                lines.append(line[-5:])
    return lines




# CDSE only allows maximum 1000 returned results per query, this function loops to get all results 
def fetch_all_data(query):
    all_data = []

    i_pages = 0
    while query:
        # Fetch the data from the current query URL
        response = requests.get(query)

        json_return = response.json()
        
        # Add the data from the current page to the list
        all_data.extend(json_return.get('value', []))
        
        # Check if there is a next page
        query = json_return.get('@odata.nextLink')
    return all_data


rx_polygon_wkt = re.compile(r'^\s*POLYGON\s*\(.*\)\s*')

# Query search if vector file is provided
# def search_by_aoi(startDate, endDate, cloudCoverMin, cloudCoverMax, aoi_path, outJson=None) -> list:
#     if rx_polygon_wkt.match(aoi_path):
#         aoi = aoi_path
#     else:
#         aoi = convert_polygon_to_WKT(aoi_path)

#     query = (
#         f"https://catalogue.dataspace.copernicus.eu/odata/v1/Products?$filter=Collection/Name eq 'SENTINEL-2' and "
#         f"Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and att/OData.CSC.StringAttribute/Value eq 'S2MSI1C') and "
#         f"ContentDate/Start ge {startDate}T00:00:00.000Z and ContentDate/Start le {endDate}T00:11:00.000Z and "
#         f"Attributes/OData.CSC.DoubleAttribute/any(att:att/Name eq 'cloudCover' and att/OData.CSC.DoubleAttribute/Value ge {cloudCoverMin:.2f}) and " 
#         f"Attributes/OData.CSC.DoubleAttribute/any(att:att/Name eq 'cloudCover' and att/OData.CSC.DoubleAttribute/Value le {cloudCoverMax:.2f}) and " 
#         f"OData.CSC.Intersects(area=geography'SRID=4326;{aoi}')"
#         f"&$top=1000" 
#     )

#     data_return = fetch_all_data(query)

#     if len(data_return) > 0:
#         print(f'Total records: {len(data_return)}')
#         if outJson is not None:
#             with open(f'{outJson}', 'w') as jsonfile:
#                 json.dump(data_return, jsonfile, indent = 4)
#             print(f'Saved to {outJson}')
#     else:
#         print(f'No record found')

#     return data_return


# Query search if .txt file is provided
def search_by_list(startDate, endDate, cloudCoverMin, cloudCoverMax, list_ids, outJson=None) -> list:
    data_return = []
    
    for tile_id in list_ids:
        query = (
            f"https://catalogue.dataspace.copernicus.eu/odata/v1/Products?$filter=Collection/Name eq 'SENTINEL-2' and "
            f"Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and att/OData.CSC.StringAttribute/Value eq 'S2MSI1C') and "
            f"Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'tileId' and att/OData.CSC.StringAttribute/Value eq '{tile_id}') and "
            f"ContentDate/Start gt {startDate}T00:00:00.000Z and ContentDate/Start lt {endDate}T00:11:00.000Z and "
            f"Attributes/OData.CSC.DoubleAttribute/any(att:att/Name eq 'cloudCover' and att/OData.CSC.DoubleAttribute/Value ge {cloudCoverMin:.2f}) and " 
            f"Attributes/OData.CSC.DoubleAttribute/any(att:att/Name eq 'cloudCover' and att/OData.CSC.DoubleAttribute/Value le {cloudCoverMax:.2f})" 
            f"&$top=1000" 
        )

        data_temp = fetch_all_data(query)
        if len(data_temp) > 0:
            data_return.extend(data_temp)

    if len(data_return) > 0:
        print(f'Total records: {len(data_return)}')
        if outJson is not None:
            with open(f'{outJson}', 'w') as jsonfile:
                json.dump(data_return, jsonfile, indent = 4)
            print(f'Saved to {outJson}')
    else:
        print(f'No record found')

    return data_return

def search_force_logs(dir_logs: Union[str, Path],
                      rx: Union[Pattern, str] = None,
                      recursive:bool = True) -> Generator[Path, None, None]:
    """
    Searches and returns FORCE sentinel-2 log files.
    :param recursive: search recursively in subdirectories, defaults to True
    :param dir_logs: path to directory containing the FORCE log files.
    :param rx: regular expression to match log files
    :return:
    """
    if rx is None:
        rx = re.compile(r'(S2|LT|LE|LC).*\.log')
    elif isinstance(rx, str):
        rx = re.compile(rx)

    assert isinstance(rx, Pattern)

    dir_logs = Path(dir_logs)
    assert dir_logs.is_dir(), f'Not a directory: {dir_logs}'
    with os.scandir(dir_logs) as search:

        for entry in search:
            if entry.is_dir() and recursive:
                for result in search_force_logs(entry.path, rx, recursive=recursive):
                    yield  result
            elif entry.is_file():
                if rx.match(entry.name):
                    yield Path(entry.path)

def main():
    check = argparseCondition()
    
    parser = argparse.ArgumentParser(prog='search', description="This tool for searching Sentinel-2 A,B,C from CDSE", add_help=True)

    parser.add_argument(
        '-d', '--daterange',
        help='Start date and end date = date range to be considered. Valid values: YYYYMMDD,YYYYMMDD',
        default=f"20150101,{datetime.now().strftime('%Y%m%d')}",
        metavar='',
        type=check.dateRangeInput
    )
    parser.add_argument(
        '-c', '--cloudcover',
        help='Percent (land) cloud cover range to be considered. Valid values: 0,100',
        default='0,100',
        metavar='',
        type=check.cloudCoverInput
    )
    parser.add_argument(
        '-n', '--no-action',
        help='Dry search without saving JSON file, output_dir is not required',
        const=True,
        default=False,
        metavar='',
        action='store_const'
    )

    parser.add_argument('-f', '--forcelogs',
                        help='Path to FORCE log file directory (Level-2 processing logs, directory will be searched recursively). '
                             'Search results will only be generated for products that haven\'t been processed by FORCE yet.',
                        default=None)

    parser.add_argument(
        'aoi',
        help='The area of interest:'
             '1) Vector file: .shp, .gpkg, .geojson, or '
             '2) .txt file that contains list of Sentinel-2 tile IDs, or'
             '3) a WKT string of the polygon',
    )
    parser.add_argument(
        'output_dir',
        nargs='?',  # Optional if `--no-action` is used
        help='The directory where the file containing the JSON metadata will be stored, if --no-action is specified, this argument is not required'
    )

    # Parse the arguments
    args = parser.parse_args()

    # Ensure that 'output_dir' is required only when 'no_action' is False
    if not args.no_action and not args.output_dir:
        parser.error("the following argument is required: output_dir")

    start_date, end_date = args.daterange
    cloud_min, cloud_max = args.cloudcover
    aoi = args.aoi

    os.path.normpath(args.aoi)
    if not os.path.isfile(aoi):
        print(f'{aoi} does not exist!')
        sys.exit()

    if aoi.endswith(tuple(['.gpkg', '.shp', '.csv'])):
        search_mode = search_by_list
        s2_list = convert_aoi_to_s2idlist(aoi)
        aoi_name = aoi
    elif aoi.endswith('.txt'):
        search_mode = search_by_list
        s2_list = read_list_id(aoi)
        aoi_name = ','.join(x for x in s2_list)
    else:
        print(f'{aoi} has a invalid extension')
        sys.exit()

    if args.no_action:
        outJson = None
    else:
        output_dir = os.path.normpath(args.output_dir)
        if output_dir.endswith('.json'):
            outJson = output_dir
        else:
            if not os.path.isdir(output_dir):
                print(f'{output_dir} does not exist!')
                sys.exit()
            else:
                Json_file_name = f"query_{datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
                outJson = os.path.join(output_dir, Json_file_name)

    info = ["Search all Sentinel-2 A,B scenes:",
            f" - From {start_date} to {end_date}",
            f" - {cloud_min} =< Cloud cover <= {cloud_max}",
            f" - AOI : {aoi_name}"]

    if args.forcelogs:
        info.append(f' - FORCE Logs: {args.forcelogs}')

    print('\n'.join(info), flush=True)

    search_results = search_mode(start_date, end_date, cloud_min, cloud_max, s2_list)

    # exclude scenes that have been already processed by FORCE
    if args.forcelogs:
        rx = re.compile(r'S2[ABCD]_MSIL1C.*\.log')
        s2_logs = list(search_force_logs(args.forcelogs, rx, recursive=True))
        s2_logs = [os.path.splitext(f.name)[0] for f in s2_logs]
        search_results_new = [r for r in search_results if r['Name'] not in s2_logs]
        print(f'Already processed by FORCE: {len(search_results)-len(search_results_new)}')
        search_results = search_results_new
        print(f'Total records left: {len(search_results)}')

    if len(search_results) > 0:
        images_size = [search_results[i]['ContentLength'] for i in range(len(search_results))]
        images_size = sum(images_size)
        images_size_gb = images_size / (1024 ** 3)
        print(f"Total data volume: {images_size_gb:.2f} GB")

    # write results to JSON file
    if outJson is not None:
        with open(f'{outJson}', 'w') as jsonfile:
            json.dump(search_results, jsonfile, indent=4)
        print(f'Saved to {outJson}')

if __name__ == '__main__':
    main()
