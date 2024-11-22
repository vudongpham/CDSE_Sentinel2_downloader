# CDSE Sentinel-2 Downloader

Search and download Sentinel-2 A,B (L1C) from https://dataspace.copernicus.eu/ using OData query

### Install with Docker image (recommended)
```
docker pull vudongpham/cdse-s2
```

### Install with conda 
1. Create new environment
```
conda env create -n cdse-s2 -f environment.yml
```
2. Activate it
```
conda activate cdse-s2
```

### Run
There are two modes <b>search</b> and <b>download</b>
#### 1. Search (no crediential required)
Search Sentinel-2 A,B data from  https://dataspace.copernicus.eu/ with some optional filterings. Returned: query results in JSON format

<i>Required arguments:</i>
- aoi\
  The area of interest. Valid input:\
  a) .txt - text file Sentinel-2 tile ID per line in the format TXXXXX or XXXXX (eg., T31UGT, 31UGT) \
  b) .shp, .gpkg, .geojson - vector file polygon geometries (points and lines are not tested yet).
  
- output_dir\
  The directory where the query result in JSON format will be stored \
  if --no-action is specified, this argument is not required

<i>Optional arguments:</i>
- -d | --daterange: Start date and end date = date range to be considered. Valid values: [YYYYMMDD,YYYYMMDD] <br><br>
- -c | --cloudcover :  Percent (land) cloud cover range to be considered. Valid values: [0,100] <br><br>
- -n | --no-action :  Dry search without saving JSON file, output_dir is not required 


Example: find all Sentinel-2 images intersect with Berlin boundary (test_data/berlin_bound.gpkg ) from 2024-01-01 to 2024-06-30 with cloud cover < 75% \
Docker
```
docker run -it --rm \
    -v $(pwd):$(pwd) \
    vudongpham/cdse-s2 search \
    --daterange 20240101,20240630 --cloudcover 0,75 \
    $(pwd)/test_data/berlin_bound.gpkg \
    $(pwd)/test_data
```

Python
```
python search.py \
    --daterange 20240101,20240630 --cloudcover 0,75 \
    $(pwd)/test_data/berlin_bound.gpkg \
    $(pwd)/test_data
```


#### 2. Download (crediential required)
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

- secret\
  Path to the file containing the CDSE account info  username (first line) and password (second line)


Example: Say you have the query result file named query_20241122T195540.json. Run the command:

Docker
```
docker run -it --rm \
    -v $(pwd):$(pwd) \
    vudongpham/cdse-s2 download \
    $(pwd)/test_data/query_20241122T195540.json \
    $(pwd)/download_dir \
    $(pwd)/test_data/secret.txt
```

Python
```
python download.py \
    $(pwd)/test_data/query_20241122T195540.json \
    $(pwd)/download_dir \
    $(pwd)/test_data/secret.txt
```

### Some notes
- At the moment, cannot filter search by sensor types (A or B), months (1,2, ..., 12), processing baseline (Sentinel-2 data from CDSE is only avalaible with baseline > 0500)
