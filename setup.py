from setuptools import setup, find_packages

setup(
    name="cdse-s2",
    version="1.00",
    packages=find_packages(), 
    install_requires=[
        "requests",
        "geopandas",

    ],
    package_data={
        'cdse': ['aux_data/*'],
    },  
    python_requires=">=3.7",  
    entry_points={
        'console_scripts': [
            'cdse-search=cdse.search:main',
            'cdse-download=cdse.download:main',
        ],
    }
)