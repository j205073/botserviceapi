#!/bin/bash
echo "開始安裝依賴套件..."
pip install -r requirements.txt
echo "依賴套件安裝完成"
cd /home/site/wwwroot
echo "當前目錄: $(pwd)"
echo "檢查 app.py 是否存在..."
ls -la app.py
echo "啟動應用程式..."
hypercorn app:app --bind 0.0.0.0:8000 --access-logfile - --error-logfile -