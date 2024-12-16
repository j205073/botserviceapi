#!/bin/bash
pip install -r requirements.txt
# python -m gunicorn --bind=0.0.0.0:8000 app:app
cd /home/site/wwwroot
hypercorn app:app --bind 0.0.0.0:8000