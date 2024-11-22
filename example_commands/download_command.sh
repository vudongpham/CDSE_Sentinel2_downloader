#!/bin/bash

# Making sure changing your <username> and <password> in secret.txt

docker run -it --rm \
    -v $(pwd):$(pwd) \
    vudongpham/cdse-s2 download \
    $(pwd)/test_data/query_20241122T195540.json \
    $(pwd)/download_dir \
    $(pwd)/test_data/secret.txt
