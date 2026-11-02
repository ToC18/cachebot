#!/bin/bash
export LD_LIBRARY_PATH=/nix/store/55byk2fn6548ni8ibgd2dyzpmk4z180w-gcc-12.2.0-lib/lib:$LD_LIBRARY_PATH
export PYTHONPATH=.:$(find .pythonlibs -type d -name "site-packages" 2>/dev/null | tr '\n' ':'):$PYTHONPATH

# Ensure packages are installed for the active python interpreter
python -m pip install --quiet -r requirements.txt

# Run main server
python main.py
