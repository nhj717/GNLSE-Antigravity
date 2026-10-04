#!/usr/bin/env bash
# Rebuild the C kernel: run from repo root with the project venv python.
set -e
PY=${PYTHON:-.venv/bin/python}
PYINC=$($PY -c 'import sysconfig;print(sysconfig.get_paths()["include"])')
NPINC=$($PY -c 'import numpy;print(numpy.get_include())')
EXT=$($PY -c 'import sysconfig;print(sysconfig.get_config_var("EXT_SUFFIX"))')
gcc -O3 -march=native -fopenmp -fPIC -shared -I"$PYINC" -I"$NPINC" \
    src/solver/accel/gnlse_c_kernel.c -o src/solver/accel/gnlse_c_kernel.so
echo built gnlse_c_kernel.so
