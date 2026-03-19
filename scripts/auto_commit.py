#!/usr/bin/env python3
import asyncio
import subprocess
import sys
import os

sys.stdout.reconfigure(encoding='utf-8')
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import get_config
from infrastructure.external.openai_client import OpenAIClient


async def generate_commit_msg():
    try:
        # Get staged diff
        diff_output = subprocess.check_output(
            ["git", "diff", "--staged"], 
            stderr=subprocess.STDOUT
        ).decode("utf-8", errors="ignore")

        if not diff_output.strip():
            print("目前沒有任何已暫存 (staged) 的變更可以產生註解。")
            sys.exit(1)

        config = get_config()
        client = OpenAIClient(config)

        prompt = f"""
你是一個資深的軟體工程師。請根據以下的 git diff 內容，自動產生一個簡潔且專業的 Git Commit 訊息。
請完全使用「繁體中文 (zh-TW)」回答。
請不要包含任何引號 (例如 ``` 標記或 ""), 直接輸出最終的純文字 Commit 訊息就好，以便腳本能直接帶入 git commit。
優先使用動詞開頭，例如「新增...」、「修正...」、「更新...」、「重構...」。
如果變更多個檔案，請挑選最重要的修改為主題，或者概括性地描述。

Diff 內容：
{diff_output}
"""

        messages = [{"role": "user", "content": prompt}]
        # Using chat_completion directly
        result = await client.chat_completion(messages=messages, max_tokens=200, temperature=0.3)
        print(result.strip())

    except Exception as e:
        print(f"產生 Commit 訊息失敗: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(generate_commit_msg())
