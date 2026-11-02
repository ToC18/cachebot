#!/bin/bash
export LD_LIBRARY_PATH=/nix/store/55byk2fn6548ni8ibgd2dyzpmk4z180w-gcc-12.2.0-lib/lib:$LD_LIBRARY_PATH
python main.py
