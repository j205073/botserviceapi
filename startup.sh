#!/bin/bash
pip install -r requirements.txt
python -m gunicorn --bind=0.0.0.0:8000 app:app