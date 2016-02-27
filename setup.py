# Always prefer setuptools over distutils
from setuptools import setup, find_packages
# To use a consistent encoding
from codecs import open
from os import path

here = path.abspath(path.dirname(__file__))

# Get the long description from the README file
with open(path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='syncrypt_desktop',

    # Versions should comply with PEP440.  For a discussion on single-sourcing
    # the version across setup.py and the project code, see
    # https://packaging.python.org/en/latest/single_source_version.html
    version='0.0.1',

    description='A Syncrypt client',
    long_description=long_description,

    # The project's main homepage.
    url='https://github.com/bakkdoor/syncrypt_desktop',

    # Author details
    author='Hannes Gräuler',
    author_email='hannes@smasi.de',

    # See https://pypi.python.org/pypi?%3Aaction=list_classifiers
    classifiers=[
        # How mature is this project? Common values are
        #   3 - Alpha
        #   4 - Beta
        #   5 - Production/Stable
        'Development Status :: 3 - Alpha',

        # Indicate who your project is intended for
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Build Tools',

        'Programming Language :: Python :: 3',
    ],

    # You can just specify the packages manually here if your project is
    # simple. Or you can use find_packages().
    packages=find_packages(exclude=['contrib', 'docs', 'tests']),

    scripts=[
        'scripts/syncrypt',
        'scripts/syncrypt_daemon',
        'scripts/syncrypt_gui',
    ],

    # Alternatively, if you want to distribute just a my_module.py, uncomment
    # this:
    #   py_modules=["my_module"],

    # List run-time dependencies here.  These will be installed by pip when
    # your project is installed. For an analysis of "install_requires" vs pip's
    # requirements files see:
    # https://packaging.python.org/en/latest/requirements.html
    install_requires=[
        'pycrypto',
        'aiofiles',
        'aiohttp',
        'umsgpack',
        'colorlog',
        'hachiko',
        'pyqt5',
        'python-snappy',
        'erlastic',
        'bert==2.1.0'
    ],

    # List additional groups of dependencies here (e.g. development
    # dependencies). You can install these using the following syntax,
    # for example:
    # $ pip install -e .[dev,test]
    extras_require={
        'dev': ['pyinstaller'],
        'test': [
            'asynctest',
            'hypothesis'
        ],
    },

    # Download bert from github (https://github.com/samuel/python-bert/issues/7)
    dependency_links = [
        'http://github.com/samuel/python-bert/tarball/master#egg=bert-2.1.0'
    ]
)
