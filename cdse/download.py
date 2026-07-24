import argparse
import json
import os
import requests
import glob
import time
import sys

# Read JSON file
def read_json_results(jsonFile):
    with open(jsonFile, 'r') as file:
        data = json.load(file)

    if len(data) < 1:
        raise TypeError("JSON file is empty or not in the correct format. Process ends!")
    try:
        images_id = [data[i]['Id'].split('.')[0] for i in range(len(data))]
        images_name = [data[i]['Name'].split('.')[0] for i in range(len(data))]
        return images_id, images_name
    except:
        raise TypeError("JSON file is empty or not in the correct format. Process ends!")

# Check if images are already exist in the downloadDir, if yes then skip
def filtering_dir(image_id, image_name, downloadDir):
    image_id_new = []
    image_name_new = []
    for i in range(len(image_name)):
        files = glob.glob(os.path.join(downloadDir, f"{image_name[i]}.*"))
        if files:
            continue
        else:
            image_id_new.append(image_id[i])
            image_name_new.append(image_name[i])
    if len(image_id_new) < 1:
        print('All images have been downloaded!')
        sys.exit()
    return image_id_new, image_name_new

# Read user name and password from secret file
def get_secret_from_file(file_dir):
    with open(file_dir, 'r') as file:
        data = [line.strip() for line in file]
    if len(data) < 2:
        print(f'{file_dir} does not have the right format, please check again!\nFirst line:<username>\nSecond line:<password>')
        sys.exit()
    user_name = data[0]
    password = data[1]
    return user_name, password

# Read user name and password from text
def get_secret_from_text(string_in):
    user_name, password = string_in.split(',')
    return user_name, password

# Get token from CDSE
def get_token(username, password):
    data = {
            "client_id": "cdse-public",
            "username": f"{username}",
            "password": f"{password}",
            "grant_type": "password",
            }

    r = requests.post("https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token", data=data)
    token = r.json()["access_token"]
    return token

# Download per image
def download(session, image_id, image_name, downloadDir):
    url = f"https://download.dataspace.copernicus.eu/odata/v1/Products({image_id})/$value"
    response = session.get(url, stream=True)
    if response.status_code == 200:
        with open(f"{downloadDir}/{image_name}.zip", "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    else:
        print(f"Failed to download {image_name}: HTTP {response.status_code}")
        print(response.text)
    return


def main():
    parser = argparse.ArgumentParser(prog='download', description="This tool for downloading Sentinel-2 A,B from CDSE", add_help=True)
    parser.add_argument(
        'jsonFile',
        help='Path to the JSON file generated from the search tool'
    )
    parser.add_argument(
        'downloadDir',
        help='The directory where the downloaded products will be stored.'
    )
    parser.add_argument(
        'secret',
        help='''
        String <username>,<password> separated by ",".
        Or path to the file containing the <username> (first line) and <password> (second line) from https://dataspace.copernicus.eu/
        ''',
    )
    args = parser.parse_args()

    jsonFile = args.jsonFile
    downloadDir= args.downloadDir
    secret = args.secret

    if not os.path.isfile(jsonFile):
        print(f'{jsonFile} does not exist!')
        sys.exit()

    if not os.path.isdir(downloadDir):
        print(f'{downloadDir} does not exist!')
        sys.exit()
    
    if  os.path.isfile(secret):
        get_secret = get_secret_from_file
    else:
        get_secret = get_secret_from_text
    
    images_id, image_names = read_json_results(jsonFile)
    images_id, image_names = filtering_dir(images_id, image_names, downloadDir)
    username, password = get_secret(secret)


    start_time = time.time()

    try:
        token = get_token(username, password)
    except:
        print("Getting token failed! Check username and password!")
        sys.exit()

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})

    print(f'Downloading {len(image_names)} images...', flush=True)
    for i in range(len(images_id)):
        current_time = time.time()
        durations = current_time - start_time
        image_path = os.path.join(downloadDir, f'{image_names}.zip')

        # CDSE token expire after 10 minutes (600 seconds), new token is refreshed after 550 seconds
        if durations > 550:
            token = get_token(username, password)
            session.headers.update({"Authorization": f"Bearer {token}"})
            start_time = time.time()
        try:
            download(session, images_id[i], image_names[i], downloadDir)
            print(f'Done {i + 1} / {len(image_names)} : {image_names[i]}', flush=True)
        except Exception as e:
            print(f"Failed to download: {image_names[i]}")
            if os.path.isfile(image_path):
                os.remove(image_path)
        except KeyboardInterrupt:
            print("Process interrupted by user. Exiting...")
            if os.path.isfile(image_path):
                os.remove(image_path)
            break

if __name__ == '__main__':
    main()
    
