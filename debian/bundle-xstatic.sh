#!/bin/bash

set -e

version=$1

TMPDIR=$(mktemp -d)
TMPDIR2=$(mktemp -d)

echo "Installing to $TMPDIR for Horizon $version"

mkdir -p $TMPDIR/lib

virtualenv $TMPDIR2
. $TMPDIR2/bin/activate
grep -i XStatic requirements.txt > $TMPDIR/requirements.txt
pip install -U pip
pip install -t $TMPDIR/lib -r $TMPDIR/requirements.txt
deactivate

(
    cd $TMPDIR/lib
    ls -lRt 
    rm -Rf *.egg-info *.dist-info
    rm -Rf *.pth
    find . -name "*.pyc" -delete
    touch xstatic/__init__.py xstatic/pkg/__init__.py
    tar -czf horizon_${version}.orig-xstatic.tar.gz *
)

mv  $TMPDIR/lib/horizon_${version}.orig-xstatic.tar.gz ..
tar xvf ../horizon_${version}.orig-xstatic.tar.gz -C ..
rm -rf $TMPDIR
