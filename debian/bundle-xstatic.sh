#!/bin/bash

set -e

version=$1

TMPDIR=$(mktemp -d)
TMPDIR2=$(mktemp -d)

echo "Installing to $TMPDIR for Horizon $version"

mkdir -p $TMPDIR/lib

virtualenv $TMPDIR2
. $TMPDIR2/bin/activate
pip install -U pip

grep -i xstatic requirements.txt > $TMPDIR/requirements.txt

pip install -t $TMPDIR/lib -r $TMPDIR/requirements.txt -c https://git.openstack.org/cgit/openstack/requirements/plain/upper-constraints.txt

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
