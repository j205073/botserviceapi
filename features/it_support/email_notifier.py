"""
Email 通知模組
透過 SMTP 發送 IT 單完成通知郵件
"""
import os
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

logger = logging.getLogger(__name__)


class EmailNotifier:
    """SMTP Email 通知服務"""

    def __init__(
        self,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        smtp_user: Optional[str] = None,
        smtp_password: Optional[str] = None,
    ):
        self.smtp_host = smtp_host or os.getenv("SMTP_HOST", "smtp.office365.com")
        self.smtp_port = smtp_port or int(os.getenv("SMTP_PORT", "25"))
        self.smtp_user = smtp_user or os.getenv("SMTP_USER", "")
        self.smtp_password = smtp_password or os.getenv("SMTP_PASSWORD", "")

    def _build_completion_email(
        self,
        to_email: str,
        issue_id: str,
        task_name: str,
        permalink_url: str = "",
    ) -> MIMEMultipart:
        """建立任務完成通知郵件"""
        msg = MIMEMultipart("alternative")
        msg["From"] = self.smtp_user
        msg["To"] = to_email
        msg["Subject"] = f"✅ IT 單 {issue_id} 已處理完成"

        # 純文字版本
        text_body = (
            f"您好，\n\n"
            f"您提交的 IT 支援單已處理完成：\n\n"
            f"  單號：{issue_id}\n"
            f"  任務：{task_name}\n"
        )
        if permalink_url:
            text_body += f"  連結：{permalink_url}\n"
        text_body += (
            f"\n如有其他問題，請在 Teams 中使用 @it 再次提單。\n\n"
            f"台灣林內 IT 服務台"
        )

        # HTML 版本
        link_html = ""
        if permalink_url:
            link_html = (
                f'<tr><td style="padding:6px 12px;color:#555;">Asana 連結</td>'
                f'<td style="padding:6px 12px;"><a href="{permalink_url}" '
                f'style="color:#4573D2;">查看任務</a></td></tr>'
            )
        html_body = f"""\
<html>
<body style="font-family:'Segoe UI',Arial,sans-serif;background:#f5f5f5;padding:20px;">
  <div style="max-width:520px;margin:0 auto;background:#fff;border-radius:8px;
              box-shadow:0 2px 8px rgba(0,0,0,0.08);overflow:hidden;">
    <div style="background:linear-gradient(135deg,#4573D2,#2ecc71);padding:24px;text-align:center;">
      <h2 style="color:#fff;margin:0;font-size:20px;">✅ IT 單已處理完成</h2>
    </div>
    <div style="padding:24px;">
      <p style="color:#333;font-size:14px;">您好，</p>
      <p style="color:#333;font-size:14px;">您提交的 IT 支援單已由 IT 人員處理完成：</p>
      <table style="width:100%;border-collapse:collapse;margin:16px 0;">
        <tr style="background:#f9f9f9;">
          <td style="padding:6px 12px;color:#555;font-weight:600;width:100px;">單號</td>
          <td style="padding:6px 12px;color:#333;">{issue_id}</td>
        </tr>
        <tr>
          <td style="padding:6px 12px;color:#555;font-weight:600;">任務</td>
          <td style="padding:6px 12px;color:#333;">{task_name}</td>
        </tr>
        {link_html}
      </table>
      <p style="color:#888;font-size:13px;margin-top:20px;">
        如有其他問題，請在 Teams 中使用 <code>@it</code> 再次提單。
      </p>
    </div>
    <div style="background:#f9f9f9;padding:12px 24px;text-align:center;">
      <p style="color:#aaa;font-size:12px;margin:0;">台灣林內 IT 服務台</p>
    </div>
  </div>
</body>
</html>"""

        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        return msg

    async def send_completion_notification(
        self,
        to_email: str,
        issue_id: str,
        task_name: str,
        permalink_url: str = "",
    ) -> bool:
        """發送任務完成通知郵件。回傳 True 表示成功。"""
        if not self.smtp_user or not self.smtp_password:
            logger.warning("SMTP 未設定，跳過 Email 通知")
            return False

        try:
            msg = self._build_completion_email(to_email, issue_id, task_name, permalink_url)

            # 使用 STARTTLS 連線（Office 365 port 25/587）
            import asyncio
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._send_smtp, msg, to_email)

            logger.info("Email 通知已發送至 %s (單號: %s)", to_email, issue_id)
            return True
        except Exception as e:
            logger.error("Email 通知發送失敗: %s", e)
            return False

    def _send_smtp(self, msg: MIMEMultipart, to_email: str) -> None:
        """同步 SMTP 發送（在 executor 中執行）"""
        print(f"📧 SMTP 連線中: {self.smtp_host}:{self.smtp_port}")
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as server:
                server.set_debuglevel(0)
                print("📧 SMTP EHLO...")
                server.ehlo()
                print("📧 SMTP STARTTLS...")
                server.starttls()
                server.ehlo()
                print(f"📧 SMTP LOGIN: {self.smtp_user}")
                server.login(self.smtp_user, self.smtp_password)
                print(f"📧 SMTP SEND: {self.smtp_user} → {to_email}")
                server.sendmail(self.smtp_user, [to_email], msg.as_string())
                print("📧 SMTP 發送完成")
        except Exception as e:
            print(f"❌ SMTP 錯誤: {type(e).__name__}: {e}")
            raise

    # ── 提單確認通知 ──────────────────────────────────────────────

    def _build_submission_email(
        self,
        to_email: str,
        issue_id: str,
        summary: str,
        category: str,
        priority: str,
        created_at: str,
        permalink_url: str = "",
        reporter_name: str = "",
    ) -> MIMEMultipart:
        """建立提單確認通知郵件"""
        msg = MIMEMultipart("alternative")
        msg["From"] = self.smtp_user
        msg["To"] = to_email
        msg["Subject"] = f"📋 IT 支援單已受理 — {issue_id}"

        display_name = reporter_name or to_email.split("@")[0]

        # 純文字版本
        text_body = (
            f"{display_name} 您好，\n\n"
            f"您的 IT 支援需求已成功提交，IT 團隊將儘速為您處理。\n\n"
            f"  📋 單號：{issue_id}\n"
            f"  📝 需求摘要：{summary}\n"
            f"  🏷️ 分類：{category}\n"
            f"  🔺 優先順序：{priority}\n"
            f"  🕐 提交時間：{created_at}\n"
        )
        if permalink_url:
            text_body += f"  🔗 Asana 連結：{permalink_url}\n"
        text_body += (
            f"\n如需補充資訊或附件，請在 Teams 中直接傳送檔案給 Bot。\n"
            f"處理完成後，系統會再次通知您。\n\n"
            f"台灣林內 IT 服務台\n"
            f"services@rinnai.com.tw"
        )

        # HTML 版本
        link_row = ""
        if permalink_url:
            link_row = (
                f'<tr style="background:#f9f9f9;">'
                f'<td style="padding:10px 16px;color:#666;font-weight:600;">🔗 Asana</td>'
                f'<td style="padding:10px 16px;"><a href="{permalink_url}" '
                f'style="color:#4573D2;text-decoration:none;">查看任務詳情</a></td></tr>'
            )

        html_body = f"""\
<html>
<body style="font-family:'Segoe UI','Microsoft JhengHei',Arial,sans-serif;background:#f0f2f5;padding:20px;margin:0;">
  <div style="max-width:560px;margin:0 auto;background:#fff;border-radius:12px;
              box-shadow:0 4px 12px rgba(0,0,0,0.1);overflow:hidden;">
    <!-- Header -->
    <div style="background:linear-gradient(135deg,#4573D2,#6C5CE7);padding:28px 24px;text-align:center;">
      <h2 style="color:#fff;margin:0;font-size:22px;letter-spacing:0.5px;">📋 IT 支援單已受理</h2>
      <p style="color:rgba(255,255,255,0.85);margin:8px 0 0;font-size:14px;">您的需求已進入處理流程</p>
    </div>

    <!-- Body -->
    <div style="padding:28px 24px;">
      <p style="color:#333;font-size:15px;margin:0 0 16px;">
        <strong>{display_name}</strong> 您好，
      </p>
      <p style="color:#555;font-size:14px;line-height:1.6;margin:0 0 20px;">
        您的 IT 支援需求已成功提交，IT 團隊將儘速為您處理。以下是您的需求資訊：
      </p>

      <!-- Info Table -->
      <table style="width:100%;border-collapse:collapse;margin:0 0 20px;border:1px solid #e8e8e8;border-radius:8px;">
        <tr style="background:#f8f9fa;">
          <td style="padding:10px 16px;color:#666;font-weight:600;width:110px;border-bottom:1px solid #e8e8e8;">📋 單號</td>
          <td style="padding:10px 16px;color:#333;font-weight:700;font-size:15px;border-bottom:1px solid #e8e8e8;">{issue_id}</td>
        </tr>
        <tr>
          <td style="padding:10px 16px;color:#666;font-weight:600;border-bottom:1px solid #e8e8e8;">📝 需求摘要</td>
          <td style="padding:10px 16px;color:#333;border-bottom:1px solid #e8e8e8;">{summary}</td>
        </tr>
        <tr style="background:#f8f9fa;">
          <td style="padding:10px 16px;color:#666;font-weight:600;border-bottom:1px solid #e8e8e8;">🏷️ 分類</td>
          <td style="padding:10px 16px;color:#333;border-bottom:1px solid #e8e8e8;">{category}</td>
        </tr>
        <tr>
          <td style="padding:10px 16px;color:#666;font-weight:600;border-bottom:1px solid #e8e8e8;">🔺 優先順序</td>
          <td style="padding:10px 16px;color:#333;border-bottom:1px solid #e8e8e8;">{priority}</td>
        </tr>
        <tr style="background:#f8f9fa;">
          <td style="padding:10px 16px;color:#666;font-weight:600;border-bottom:1px solid #e8e8e8;">🕐 提交時間</td>
          <td style="padding:10px 16px;color:#333;border-bottom:1px solid #e8e8e8;">{created_at}</td>
        </tr>
        {link_row}
      </table>

      <!-- Tip Box -->
      <div style="background:#EBF5FB;border-left:4px solid #4573D2;padding:12px 16px;border-radius:0 6px 6px 0;margin:0 0 16px;">
        <p style="color:#2C3E50;font-size:13px;margin:0;line-height:1.5;">
          💡 <strong>小提示：</strong>如需補充資訊或附件，請在 Teams 中直接傳送檔案給 Bot 即可自動附加至此工單。
        </p>
      </div>

      <p style="color:#888;font-size:13px;margin:0;line-height:1.5;">
        處理完成後，系統會再次通知您。感謝您的耐心等候！
      </p>
    </div>

    <!-- Footer -->
    <div style="background:#f8f9fa;padding:16px 24px;text-align:center;border-top:1px solid #e8e8e8;">
      <p style="color:#aaa;font-size:12px;margin:0;">台灣林內 IT 服務台 · services@rinnai.com.tw</p>
    </div>
  </div>
</body>
</html>"""

        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        return msg

    async def send_submission_notification(
        self,
        to_email: str,
        issue_id: str,
        summary: str,
        category: str = "",
        priority: str = "",
        created_at: str = "",
        permalink_url: str = "",
        reporter_name: str = "",
    ) -> bool:
        """發送提單確認通知郵件。回傳 True 表示成功。"""
        if not self.smtp_user or not self.smtp_password:
            logger.warning("SMTP 未設定，跳過提單確認 Email")
            return False

        try:
            msg = self._build_submission_email(
                to_email, issue_id, summary, category, priority,
                created_at, permalink_url, reporter_name,
            )

            import asyncio
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._send_smtp, msg, to_email)

            logger.info("提單確認 Email 已發送至 %s (單號: %s)", to_email, issue_id)
            return True
        except Exception as e:
            logger.error("提單確認 Email 發送失敗: %s", e)
            return False

    async def send_custom_notification(
        self,
        to_email: str,
        subject: str,
        body_text: str,
    ) -> bool:
        """發送自訂內容的通知郵件。"""
        if not self.smtp_user or not self.smtp_password:
            return False

        try:
            msg = MIMEMultipart()
            msg["From"] = self.smtp_user
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(body_text, "plain", "utf-8"))

            import asyncio
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._send_smtp, msg, to_email)
            return True
        except Exception as e:
            logger.error("自訂 Email 通知發送失敗: %s", e)
            return False
