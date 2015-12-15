# Syncrypt platform independent desktop client

Currently requires Python 3.

Setup in virtualenv:

    virtualenv .
    bin/pip install -e .

Init current directory (will ask for username and password):

    bin/syncrypt init

Pull current directory:

    bin/syncrypt pull

Push current directory:

    bin/syncrypt push

Watch current directory:

    bin/syncrypt watch

Alternate directory can be specified with ``-d``:

    bin/syncrypt -d ~/myfolder watch

Run tests:

    bin/pip install -e '.[test]'
    bin/python tests/test_all.py
