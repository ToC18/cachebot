#!/bin/bash
export LD_LIBRARY_PATH=/nix/store/55byk2fn6548ni8ibgd2dyzpmk4z180w-gcc-12.2.0-lib/lib:$LD_LIBRARY_PATH

# Clean up mixed-version binary wheels
rm -rf .pythonlibs

# Clean install for active python
python3 -m pip install -r requirements.txt

# Start production server
python3 main.py
