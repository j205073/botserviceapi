"""
快速測試 SMTP Email 發送
用法: python test_email.py
"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from features.it_support.email_notifier import EmailNotifier


async def main():
    notifier = EmailNotifier()
    print(f"SMTP: {notifier.smtp_host}:{notifier.smtp_port}")
    print(f"From: {notifier.smtp_user}")
    print(f"Password: {'*' * len(notifier.smtp_password)} ({len(notifier.smtp_password)} chars)")
    print()

    to = "juncheng.liu@rinnai.com.tw"
    print(f"發送測試郵件至 {to} ...")

    ok = await notifier.send_submission_notification(
        to_email=to,
        issue_id="IT202602110001",
        summary="測試需求 - 電腦無法開機",
        category="硬體問題",
        priority="P2",
        created_at="2026-02-11 10:20 台北時間",
        permalink_url="https://app.asana.com/0/test/test",
        reporter_name="劉俊成",
    )

    print(f"\n結果: {'✅ 成功！請檢查信箱' if ok else '❌ 失敗'}")


if __name__ == "__main__":
    asyncio.run(main())
