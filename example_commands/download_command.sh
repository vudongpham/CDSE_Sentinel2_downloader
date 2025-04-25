#!/bin/bash

# Making sure changing your <username> and <password> in secret.txt

docker run -it --rm \
    -v $(pwd):$(pwd) \
    vudongpham/cdse-s2 cdse-download \
    $(pwd)/test_data/query.json \
    $(pwd)/download_dir \
    $(pwd)/test_data/secret.txt
