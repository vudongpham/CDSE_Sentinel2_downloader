"""Search Sentinel-2 products in the Copernicus Data Space Ecosystem (CDSE) catalogue."""
import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from typing import Generator, Iterable, List, Optional, Pattern, Sequence, Union

from cdse._http import make_session

CATALOGUE_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
PAGE_SIZE = 1000  # maximum number of results CDSE returns per page

PRODUCT_TYPES = {"L1C": "S2MSI1C", "L2A": "S2MSI2A"}
SATELLITES = ("S2A", "S2B", "S2C", "S2D")

rx_tile_id = re.compile(r"^T?(\d{2}[A-Z]{3})$")


# ---------------------------------------------------------------------------
# Argument parsing helpers
# ---------------------------------------------------------------------------
class argparseCondition():
    def dateRangeInput(self, value):
        if not re.match(r'^\d{8},\d{8}$', value):
            raise argparse.ArgumentTypeError(
                f"Invalid date range format: {value}. Expected format is YYYYMMDD,YYYYMMDD.")
        dates = []
        for d in value.split(','):
            try:
                dates.append(datetime.strptime(d, "%Y%m%d").date())
            except ValueError:
                raise argparse.ArgumentTypeError(f"Invalid date {d}")
        start, end = dates
        if start > end:
            raise argparse.ArgumentTypeError(f"Start date {start} is after end date {end}")
        return start.isoformat(), end.isoformat()

    def cloudCoverInput(self, value):
        try:
            x, y = (int(v) for v in value.split(','))
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"Invalid input: {value}. Expected format is 'x,y' with x and y between 0 and 100.")
        if not (0 <= x <= 100 and 0 <= y <= 100) or x > y:
            raise argparse.ArgumentTypeError(
                f"Invalid input: {value}. Expected 0 <= x <= y <= 100.")
        return x, y

    def monthsInput(self, value):
        try:
            months = sorted({int(m) for m in value.split(',') if m.strip()})
        except ValueError:
            raise argparse.ArgumentTypeError(f"Invalid months: {value}. Expected e.g. 6,7,8")
        if not months or any(m < 1 or m > 12 for m in months):
            raise argparse.ArgumentTypeError(f"Invalid months: {value}. Values must be in 1..12")
        return months

    def satelliteInput(self, value):
        sats = sorted({s.strip().upper() for s in value.split(',') if s.strip()})
        sats = [s if s.startswith('S2') else f'S2{s}' for s in sats]
        bad = [s for s in sats if s not in SATELLITES]
        if not sats or bad:
            raise argparse.ArgumentTypeError(
                f"Invalid satellite(s): {value}. Valid values: {','.join(SATELLITES)}")
        return sats


# ---------------------------------------------------------------------------
# AOI -> Sentinel-2 tile IDs
# ---------------------------------------------------------------------------
def convert_aoi_to_s2idlist(aoi_path) -> List[str]:
    """Return the sorted list of Sentinel-2 tile IDs (e.g. '32UQD') whose footprint
    overlaps the polygons of a vector file."""
    import geopandas as gpd  # imported lazily: only needed for vector AOIs

    aoi = gpd.read_file(aoi_path)
    if aoi.empty:
        return []
    if aoi.crs is None:
        raise ValueError(f"{aoi_path} has no coordinate reference system")
    aoi = aoi.to_crs("EPSG:4326")
    aoi_geom = aoi.geometry.union_all() if hasattr(aoi.geometry, 'union_all') else aoi.geometry.unary_union

    # Only read the grid features inside the AOI bounding box instead of all ~57k tiles
    s2_path = files("cdse.aux_data").joinpath("sentinel2_grid.gpkg")
    s2_grid = gpd.read_file(s2_path, bbox=tuple(aoi.total_bounds))
    if s2_grid.empty:
        return []

    hits = s2_grid.intersects(aoi_geom) & ~s2_grid.touches(aoi_geom)
    return sorted({x.strip()[-5:] for x in s2_grid.loc[hits, 'PRFID']})


def read_list_id(aoi_path) -> List[str]:
    """Read Sentinel-2 tile IDs (one per line, 'T32UQD' or '32UQD') from a text file."""
    ids = []
    with open(aoi_path, 'r') as file:
        for line in file:
            line = line.strip().upper()
            if len(line) >= 5:
                ids.append(line[-5:])
    return list(dict.fromkeys(ids))  # drop duplicates, keep order


def parse_tile_ids(value: str) -> Optional[List[str]]:
    """Parse a comma separated tile list such as 'T32UQD,33UUU'. Returns None if invalid."""
    ids = []
    for part in value.split(','):
        m = rx_tile_id.match(part.strip().upper())
        if not m:
            return None
        ids.append(m.group(1))
    return list(dict.fromkeys(ids))


# ---------------------------------------------------------------------------
# Catalogue queries
# ---------------------------------------------------------------------------
def build_query(tile_id: str, startDate: str, endDate: str,
                cloudCoverMin: float = 0, cloudCoverMax: float = 100,
                productType: str = 'S2MSI1C') -> str:
    """Build the OData query URL for one tile. Dates are 'YYYY-MM-DD' and inclusive."""
    end_exclusive = (date.fromisoformat(endDate) + timedelta(days=1)).isoformat()
    filters = [
        "Collection/Name eq 'SENTINEL-2'",
        "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and "
        f"att/OData.CSC.StringAttribute/Value eq '{productType}')",
        "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'tileId' and "
        f"att/OData.CSC.StringAttribute/Value eq '{tile_id}')",
        f"ContentDate/Start ge {startDate}T00:00:00.000Z",
        f"ContentDate/Start lt {end_exclusive}T00:00:00.000Z",
    ]
    if cloudCoverMin > 0:
        filters.append("Attributes/OData.CSC.DoubleAttribute/any(att:att/Name eq 'cloudCover' and "
                       f"att/OData.CSC.DoubleAttribute/Value ge {cloudCoverMin:.2f})")
    if cloudCoverMax < 100:
        filters.append("Attributes/OData.CSC.DoubleAttribute/any(att:att/Name eq 'cloudCover' and "
                       f"att/OData.CSC.DoubleAttribute/Value le {cloudCoverMax:.2f})")
    return (f"{CATALOGUE_URL}?$filter={' and '.join(filters)}"
            f"&$orderby=ContentDate/Start asc&$top={PAGE_SIZE}")


def fetch_all_data(query: str, session=None) -> list:
    """Follow '@odata.nextLink' pagination and return all products of a query."""
    session = session or make_session()
    all_data = []
    while query:
        response = session.get(query, timeout=120)
        response.raise_for_status()
        json_return = response.json()
        all_data.extend(json_return.get('value', []))
        query = json_return.get('@odata.nextLink')
    return all_data


def search_by_list(startDate, endDate, cloudCoverMin, cloudCoverMax, list_ids,
                   outJson=None, productType='S2MSI1C', workers=4, verbose=True) -> list:
    """Search all products for a list of tile IDs. Tiles are queried in parallel."""
    session = make_session(pool_size=max(workers, 1))
    queries = [build_query(t, startDate, endDate, cloudCoverMin, cloudCoverMax, productType)
               for t in list_ids]

    def run(args):
        tile_id, query = args
        data = fetch_all_data(query, session)
        if verbose:
            print(f'  {tile_id}: {len(data)} products', flush=True)
        return data

    with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
        results = list(pool.map(run, zip(list_ids, queries)))

    # Flatten and drop duplicates (same product returned for several tiles)
    seen = set()
    data_return = []
    for data in results:
        for item in data:
            if item.get('Id') not in seen:
                seen.add(item.get('Id'))
                data_return.append(item)
    data_return.sort(key=lambda r: (r.get('ContentDate', {}).get('Start', ''), r.get('Name', '')))

    if outJson is not None:
        write_json(data_return, outJson)
    return data_return


def filter_results(results: Iterable[dict], satellites: Optional[Sequence[str]] = None,
                   months: Optional[Sequence[int]] = None, online_only: bool = False) -> list:
    """Client side filters by satellite (S2A, S2B, ...), acquisition month and online status."""
    out = []
    for r in results:
        name = r.get('Name', '')
        if satellites and name[:3] not in satellites:
            continue
        if months:
            start = r.get('ContentDate', {}).get('Start', '')
            if len(start) < 7 or int(start[5:7]) not in months:
                continue
        if online_only and r.get('Online') is False:
            continue
        out.append(r)
    return out


def write_json(data, outJson):
    with open(outJson, 'w') as jsonfile:
        json.dump(data, jsonfile, indent=4)
    print(f'Saved to {outJson}')


# ---------------------------------------------------------------------------
# FORCE logs
# ---------------------------------------------------------------------------
def search_force_logs(dir_logs: Union[str, Path],
                      rx: Union[Pattern, str] = None,
                      recursive: bool = True) -> Generator[Path, None, None]:
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
                yield from search_force_logs(entry.path, rx, recursive=recursive)
            elif entry.is_file():
                if rx.match(entry.name):
                    yield Path(entry.path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None):
    check = argparseCondition()

    parser = argparse.ArgumentParser(prog='cdse-search',
                                     description="Search Sentinel-2 A,B,C,D products in CDSE", add_help=True)
    parser.add_argument(
        '-d', '--daterange',
        help='Start date and end date (both inclusive). Valid values: YYYYMMDD,YYYYMMDD',
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
        '-p', '--product',
        help='Processing level: L1C (default) or L2A',
        default='L1C',
        choices=sorted(PRODUCT_TYPES),
        type=str.upper,
    )
    parser.add_argument(
        '-s', '--satellite',
        help='Only keep these satellites, e.g. S2A,S2B (default: all)',
        default=None,
        metavar='',
        type=check.satelliteInput
    )
    parser.add_argument(
        '-m', '--months',
        help='Only keep acquisitions from these months, e.g. 6,7,8 (default: all)',
        default=None,
        metavar='',
        type=check.monthsInput
    )
    parser.add_argument(
        '-w', '--workers',
        help='Number of parallel catalogue requests (default: 4)',
        default=4,
        metavar='',
        type=int
    )
    parser.add_argument(
        '-n', '--no-action',
        help='Dry search without saving JSON file, output_dir is not required',
        action='store_true'
    )
    parser.add_argument('-f', '--forcelogs',
                        help='Path to FORCE log file directory (Level-2 processing logs, directory will be searched recursively). '
                             'Search results will only be generated for products that haven\'t been processed by FORCE yet.',
                        default=None)
    parser.add_argument(
        'aoi',
        help='The area of interest: '
             '1) vector file (.shp, .gpkg, .geojson, ...), or '
             '2) .txt file that contains a list of Sentinel-2 tile IDs, or '
             '3) comma separated tile IDs, e.g. T32UQD,33UUU',
    )
    parser.add_argument(
        'output_dir',
        nargs='?',  # Optional if `--no-action` is used
        help='Directory (or .json file path) where the JSON metadata will be stored; '
             'not required with --no-action'
    )

    args = parser.parse_args(argv)

    if not args.no_action and not args.output_dir:
        parser.error("the following argument is required: output_dir")
    if args.workers < 1:
        parser.error("--workers must be >= 1")

    start_date, end_date = args.daterange
    cloud_min, cloud_max = args.cloudcover
    aoi = args.aoi

    if os.path.isfile(aoi):
        if aoi.lower().endswith('.txt'):
            s2_list = read_list_id(aoi)
        else:
            try:
                s2_list = convert_aoi_to_s2idlist(aoi)
            except Exception as e:
                sys.exit(f'Could not read {aoi} as a vector file: {e}')
        aoi_name = aoi
    else:
        s2_list = parse_tile_ids(aoi)
        if s2_list is None:
            sys.exit(f'{aoi} is neither an existing file nor a list of Sentinel-2 tile IDs!')
        aoi_name = aoi

    if not s2_list:
        sys.exit(f'No Sentinel-2 tile found for {aoi}')

    if args.no_action:
        outJson = None
    else:
        output_dir = os.path.normpath(args.output_dir)
        if output_dir.lower().endswith('.json'):
            parent = os.path.dirname(output_dir) or '.'
            if not os.path.isdir(parent):
                sys.exit(f'{parent} does not exist!')
            outJson = output_dir
        else:
            if not os.path.isdir(output_dir):
                sys.exit(f'{output_dir} does not exist!')
            outJson = os.path.join(output_dir, f"query_{datetime.now().strftime('%Y%m%dT%H%M%S')}.json")

    info = [f"Search Sentinel-2 {args.product} scenes:",
            f" - From {start_date} to {end_date}",
            f" - {cloud_min} <= Cloud cover <= {cloud_max}",
            f" - AOI : {aoi_name}",
            f" - Tiles ({len(s2_list)}): {','.join(s2_list)}"]
    if args.satellite:
        info.append(f" - Satellites: {','.join(args.satellite)}")
    if args.months:
        info.append(f" - Months: {','.join(map(str, args.months))}")
    if args.forcelogs:
        info.append(f' - FORCE Logs: {args.forcelogs}')
    print('\n'.join(info), flush=True)

    try:
        search_results = search_by_list(start_date, end_date, cloud_min, cloud_max, s2_list,
                                        productType=PRODUCT_TYPES[args.product], workers=args.workers)
    except Exception as e:
        sys.exit(f'Search failed: {e}')

    search_results = filter_results(search_results, args.satellite, args.months)
    print(f'Total records: {len(search_results)}')

    # exclude scenes that have been already processed by FORCE
    if args.forcelogs:
        rx = re.compile(r'S2[ABCD]_MSIL1C.*\.log')
        s2_logs = {os.path.splitext(f.name)[0] for f in search_force_logs(args.forcelogs, rx, recursive=True)}
        search_results_new = [r for r in search_results if r['Name'] not in s2_logs]
        print(f'Already processed by FORCE: {len(search_results) - len(search_results_new)}')
        search_results = search_results_new
        print(f'Total records left: {len(search_results)}')

    if search_results:
        images_size_gb = sum(r.get('ContentLength', 0) for r in search_results) / (1024 ** 3)
        print(f"Total data volume: {images_size_gb:.2f} GB")

    if outJson is not None:
        write_json(search_results, outJson)


if __name__ == '__main__':
    main()
