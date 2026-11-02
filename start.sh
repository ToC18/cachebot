#!/bin/bash
export LD_LIBRARY_PATH=/nix/store/55byk2fn6548ni8ibgd2dyzpmk4z180w-gcc-12.2.0-lib/lib:$LD_LIBRARY_PATH

# Verify key dependencies exist, otherwise install
if ! python3 -c "import fastapi, aiogram, asyncpg" &>/dev/null; then
    python3 -m pip install -r requirements.txt
fi

# Run CacheBot server
python3 main.py
