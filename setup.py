from setuptools import setup, find_packages

setup(
    name="cdse-s2",
    version="1.1.0",
    description="Search and download Sentinel-2 data from the Copernicus Data Space Ecosystem (CDSE)",
    packages=find_packages(exclude=["tests"]),
    install_requires=[
        "requests>=2.25",
        "urllib3>=1.26",
        "geopandas>=0.12",
    ],
    package_data={
        'cdse': ['aux_data/*'],
    },
    python_requires=">=3.8",
    entry_points={
        'console_scripts': [
            'cdse-search=cdse.search:main',
            'cdse-download=cdse.download:main',
        ],
    }
)
