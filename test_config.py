#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os

print("測試環境變數切換功能...")

# 測試 Azure OpenAI 配置
os.environ['USE_AZURE_OPENAI'] = 'true'
print("\n=== Azure OpenAI 配置 ===")
USE_AZURE_OPENAI = os.getenv('USE_AZURE_OPENAI', 'true').lower() == 'true'
print(f'USE_AZURE_OPENAI: {USE_AZURE_OPENAI}')
if USE_AZURE_OPENAI:
    print("將使用 Azure OpenAI - o1-mini")
else:
    print("將使用 OpenAI 直接 API - gpt-4")

# 測試 OpenAI 直接 API 配置
os.environ['USE_AZURE_OPENAI'] = 'false'
print("\n=== OpenAI 直接 API 配置 ===")
USE_AZURE_OPENAI = os.getenv('USE_AZURE_OPENAI', 'true').lower() == 'true'
print(f'USE_AZURE_OPENAI: {USE_AZURE_OPENAI}')
if USE_AZURE_OPENAI:
    print("將使用 Azure OpenAI - o1-mini")
else:
    print("將使用 OpenAI 直接 API - gpt-4")

print("\n配置切換測試完成")