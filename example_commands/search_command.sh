#!/bin/bash

docker run -it --rm \
    -v $(pwd):$(pwd) \
    vudongpham/cdse-s2 cdse-search \
    --daterange 20240101,20240130 --cloudcover 0,75 \
    $(pwd)/test_data/berlin_boundary.gpkg \
    $(pwd)/test_data