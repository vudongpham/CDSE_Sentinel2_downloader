#!/bin/bash

# Making sure changing your <username> and <password> in secret.txt

docker run -it --rm \
    -v $(pwd):$(pwd) \
    cdse-s2 download \
    $(pwd)/test_data/test.json \
    $(pwd)/test_data/download_dir \
    $(pwd)/test_data/test_data/secret.txt