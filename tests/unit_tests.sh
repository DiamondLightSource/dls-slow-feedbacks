#!/bin/bash

# There are a variety of tests in this directory: some need
# python soft IOC, some are fairly simple unit tests and
# some are just demos that don't test automatically.

cd $(dirname $0)

PYTHONPATH=$PYTHONPATH:../python

PYIOC=/dls_sw/prod/R3.14.12.3/support/pythonSoftIoc/2-5/pythonIoc

# Requires python soft IOC
$PYIOC test_tunefb_server.py

# Just uses pytest
py.test test_sofb.py
py.test mml_sql_test.py
