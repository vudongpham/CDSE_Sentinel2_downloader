> [!IMPORTANT]  
> Using WKT string for `cdse-search` is no longer supported! 

# CDSE Sentinel-2 Downloader

Search and download Sentinel-2 A,B,C (L1C or L2A) from https://dataspace.copernicus.eu/ using OData query.

Features: parallel catalogue search, parallel downloads (up to 4, the CDSE limit), automatic retries with backoff, automatic token refresh, size/MD5 verification and safe resuming (unfinished downloads are kept as `.part` files and never mistaken for complete ones).

### Install with Docker image
```
docker pull vudongpham/cdse-s2:latest
```
### Install with Singularity
```
singularity pull -F ~/cdse-s2_latest.sif docker://vudongpham/cdse-s2:latest
```

### Install with python
With Git installed in your machine
```
python -m pip install git+https://github.com/vudongpham/CDSE_Sentinel2_downloader.git
```
Without Git
```
python -m pip install https://github.com/vudongpham/CDSE_Sentinel2_downloader/archive/refs/heads/main.zip
```


### Run
There are two modes <b>search</b> and <b>download</b>
#### 1. Search (no credential required)
Search Sentinel-2 A,B data from  https://dataspace.copernicus.eu/ with some optional filterings. Returned: query results in JSON format

<i>Required arguments:</i>
- aoi\
  The area of interest. Valid input:\
  a) .txt - text file Sentinel-2 tile ID per line in the format TXXXXX or XXXXX (eg., T31UGT, 31UGT) \
  b) .shp, .gpkg, .geojson - vector file polygon geometries (any CRS) \
  c) comma separated tile IDs directly, e.g. `T32UQD,33UUU`
  
- output_dir\
  The directory where the query result in JSON format will be stored \
  if --no-action is specified, this argument is not required

<i>Optional arguments:</i>
- -d | --daterange: Start date and end date (both inclusive). Valid values: [YYYYMMDD,YYYYMMDD]
- -c | --cloudcover:  Percent (land) cloud cover range to be considered. Valid values: [0,100]
- -p | --product: Processing level, `L1C` (default) or `L2A`
- -s | --satellite: Only keep some satellites, e.g. `S2A,S2C` (default: all)
- -m | --months: Only keep acquisitions from some months, e.g. `6,7,8` (default: all)
- -w | --workers: Number of parallel catalogue requests (default: 4)
- -n | --no-action:  Dry search without saving JSON file, output_dir is not required
- -f | --forcelogs: Path to FORCE log file directory (Level-2 processing logs, directory will be searched recursively). 
                    Search results will only be generated for products that haven't been processed by FORCE yet.



Example: find all Sentinel-2 images intersect with Berlin boundary (test_data/berlin_bound.gpkg ) from 2024-01-01 to 2024-06-30 with cloud cover < 75%. \
Docker
```
docker run -it --rm \
    -v $(pwd):$(pwd) \
    vudongpham/cdse-s2 cdse-search \
    --daterange 20240101,20240630 --cloudcover 0,75 \
    $(pwd)/test_data/berlin_boundary.gpkg \
    $(pwd)/test_data
```

Python
```
cdse-search \
    --daterange 20240101,20240630 --cloudcover 0,75 \
    $(pwd)/test_data/berlin_boundary.gpkg \
    $(pwd)/test_data
```

Query result looks something like this
```
...
"@odata.mediaContentType": "application/octet-stream",
        "Id": "fd292acb-9337-4842-84f1-f2c69ad02486",
        "Name": "S2A_MSIL1C_20240108T101401_N0510_R022_T32UQD_20240108T105807.SAFE",
        "ContentType": "application/octet-stream",
        "ContentLength": 606111777,
        "OriginDate": "2024-01-08T12:18:07.491000Z",
        "PublicationDate": "2024-01-08T12:45:53.969146Z",
        "ModificationDate": "2024-03-12T12:13:30.930987Z",
        "Online": true,
        "EvictionDate": "9999-12-31T23:59:59.999999Z",
        "S3Path": "/eodata/Sentinel-2/MSI/L1C/2024/01/08/S2A_MSIL1C_20240108T101401_N0510_R022_T32UQD_20240108T105807.SAFE",
...
```


#### 2. Download (credential required)
Download data data from the query JSON file from <b>search</b> function. <br><br>
<b>NOTE:</b> First, you need to have account on https://dataspace.copernicus.eu/.<br>
Then store the account information in a file, for example: secret.txt. This file should contains only two lines, first is username, second is password
```
username
password
```

<i>Download requires three arguments:</i>
- jsonFile\
  Path to the JSON file generated from the search function.
  
- downloadDir\
  The directory where the downloaded products will be stored.

- secret (optional)\
  Path to the file containing the <username> (first line) and <password> (second line) from https://dataspace.copernicus.eu/ \
  Or string username,password separated by ",". \
  If omitted, the `CDSE_USERNAME` and `CDSE_PASSWORD` environment variables are used (recommended: the password does not end up in your shell history).

<i>Optional arguments:</i>
- -w | --workers: Number of parallel downloads, 1-4 (default: 2)
- -r | --retries: Attempts per product before giving up (default: 3)
- --checksum: Verify the MD5 checksum of every download against the JSON metadata

Products already present in downloadDir are skipped, so re-running the same command resumes an interrupted or partially failed job. The command exits with a non-zero code if any product failed.


Example: Say you have the query result file named query.json. Run the command:

Docker
```
docker run -it --rm \
    -v $(pwd):$(pwd) \
    vudongpham/cdse-s2 cdse-download \
    $(pwd)/test_data/query.json \
    $(pwd)/download_dir \
    $(pwd)/test_data/secret.txt
```

Python
```
cdse-download \
    $(pwd)/test_data/query.json \
    $(pwd)/download_dir \
    $(pwd)/test_data/secret.txt
```

### Running the tests
```
python -m pip install pytest
python -m pytest tests
```
Tests run offline; set `CDSE_ONLINE_TESTS=1` to also query the real CDSE catalogue.

### Some notes
- Cannot filter search by processing baseline (Sentinel-2 data from CDSE is only avalaible with baseline > 0500)
