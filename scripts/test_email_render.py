import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from features.it_support.email_notifier import EmailNotifier

async def test_render():
    notifier = EmailNotifier(
        smtp_user="test@rinnai.com.tw",
        smtp_password="password"
    )
    
    # Test submission email
    msg_sub = notifier._build_submission_email(
        to_email="user@rinnai.com.tw",
        issue_id="IT202402110001",
        summary="我的電腦藍屏了，請協助處理。",
        category="硬體故障",
        priority="P1",
        created_at="2024-02-11 10:00",
        permalink_url="https://asana.com/test",
        reporter_name="張小明"
    )
    
    # Test completion email
    msg_comp = notifier._build_completion_email(
        to_email="user@rinnai.com.tw",
        issue_id="IT202402110001",
        task_name="我的電腦藍屏了，請協助處理。",
        permalink_url="https://asana.com/test"
    )
    
    output_dir = Path("temp_verify")
    output_dir.mkdir(exist_ok=True)
    
    def save_html(msg, filename):
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                with open(output_dir / filename, "w", encoding="utf-8") as f:
                    f.write(part.get_payload(decode=True).decode("utf-8"))
                print(f"Saved {filename}")

    save_html(msg_sub, "submission.html")
    save_html(msg_comp, "completion.html")

if __name__ == "__main__":
    asyncio.run(test_render())
