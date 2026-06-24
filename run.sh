#!/bin/bash
set -e

python3 build_db.py
python3 app.py
