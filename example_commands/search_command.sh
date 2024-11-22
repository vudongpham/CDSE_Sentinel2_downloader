#!/bin/bash

docker run -it --rm \
    -v $(pwd):$(pwd) \
    cdse-s2 search\
    --daterange 20170101,20171231 --cloudcover 0,75 \
    $(pwd)/test_data/test_bound3.gpkg \
    $(pwd)/test_data