#!/bin/bash

docker run -it --rm \
    -v $(pwd):$(pwd) \
    vudongpham/cdse-s2 search \
    --daterange 20240101,20240630 --cloudcover 0,75 \
    $(pwd)/test_data/berlin_bound.gpkg \
    $(pwd)/test_data