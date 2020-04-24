#!/bin/bash

set -e

version=$1

TMPDIR=$(mktemp -d)

echo "Installing to $TMPDIR for Horizon $version"

mkdir -p $TMPDIR/lib

grep -i xstatic requirements.txt > $TMPDIR/requirements.txt

pip install --system -t $TMPDIR/lib -r $TMPDIR/requirements.txt -c https://git.openstack.org/cgit/openstack/requirements/plain/upper-constraints.txt

(
    cd $TMPDIR/lib
    ls -lRt
    rm -Rf *.egg-info *.dist-info
    rm -Rf *.pth
    find . -name "*.pyc" -delete
    touch xstatic/__init__.py xstatic/pkg/__init__.py
    tar -czf horizon_${version}.orig-xstatic.tar.gz *
)

mkdir -p ../build-area
mv  $TMPDIR/lib/horizon_${version}.orig-xstatic.tar.gz ../build-area
rm -rf $TMPDIR
