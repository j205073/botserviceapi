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
            f"台灣林內-資訊課"
        )

        # HTML 版本
        link_button = ""
        if permalink_url:
            link_button = (
                f'<div style="text-align: center; margin: 32px 0;">'
                f'<a href="{permalink_url}" style="background-color: #0052CC; color: #ffffff; '
                f'padding: 12px 24px; text-decoration: none; border-radius: 6px; '
                f'font-weight: 600; display: inline-block;">查看任務詳情</a>'
                f'</div>'
            )
        
        html_body = f"""\
<html>
<body style="font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #F4F5F7; padding: 40px 20px; margin: 0;">
  <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; 
              box-shadow: 0 4px 20px rgba(9, 30, 66, 0.15); overflow: hidden;">
    <!-- Header -->
    <div style="background: linear-gradient(135deg, #0052CC, #0747A6); padding: 32px 24px; text-align: center;">
      <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: 600; letter-spacing: 2px;">✅ IT 單已處理完成</h1>
    </div>
    
    <!-- Content -->
    <div style="padding: 40px 32px;">
      <p style="color: #172B4D; font-size: 16px; line-height: 1.6; margin-top: 0;">您好，</p>
      <p style="color: #42526E; font-size: 16px; line-height: 1.6;">您提交的 IT 支援需求已由服務台工程師處理完成：</p>
      
      <div style="background-color: #FAFBFC; border: 1px solid #DFE1E6; border-radius: 8px; padding: 24px; margin: 32px 0;">
        <table style="width: 100%; border-collapse: collapse;">
          <tr>
            <td style="padding: 8px 0; color: #6B778C; font-size: 14px; font-weight: 600; width: 100px;">支援單號</td>
            <td style="padding: 8px 0; color: #172B4D; font-size: 15px; font-weight: 600;">{issue_id}</td>
          </tr>
          <tr>
            <td style="padding: 8px 0; color: #6B778C; font-size: 14px; font-weight: 600;">需求摘要</td>
            <td style="padding: 8px 0; color: #172B4D; font-size: 15px;">{task_name}</td>
          </tr>
        </table>
      </div>

      {link_button}

      <div style="padding: 24px; background-color: #EBF5FB; border-left: 4px solid #0052CC; border-radius: 4px; margin-top: 32px;">
        <p style="color: #0747A6; font-size: 14px; margin: 0; line-height: 1.5;">
          <strong>需要進一步協助？</strong><br>
          如問題尚未解決或有後續需求，請在 Teams 中使用 <code>@it</code> 重新提單。
        </p>
      </div>
    </div>

    <!-- Footer -->
    <div style="background-color: #F4F5F7; padding: 24px; text-align: center; border-top: 1px solid #DFE1E6;">
      <p style="color: #6B778C; font-size: 12px; margin: 0;">此為系統自動發送郵件，請勿直接回覆。</p>
      <p style="color: #6B778C; font-size: 12px; margin: 8px 0 0;">台灣林內-資訊課</p>
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
            f"台灣林內-資訊課\n"
            f"services@rinnai.com.tw"
        )

        # HTML 版本
        link_button = ""
        if permalink_url:
            link_button = (
                f'<div style="text-align: center; margin: 32px 0;">'
                f'<a href="{permalink_url}" style="background-color: #0052CC; color: #ffffff; '
                f'padding: 12px 24px; text-decoration: none; border-radius: 6px; '
                f'font-weight: 600; display: inline-block;">進入任務中心</a>'
                f'</div>'
            )

        html_body = f"""\
<html>
<body style="font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #F4F5F7; padding: 40px 20px; margin: 0;">
  <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; 
              box-shadow: 0 4px 20px rgba(9, 30, 66, 0.15); overflow: hidden;">
    <!-- Header -->
    <div style="background: linear-gradient(135deg, #0052CC, #0747A6); padding: 40px 24px; text-align: center;">
      <h1 style="color: #ffffff; margin: 0; font-size: 26px; font-weight: 700; letter-spacing: 2px;">📋 IT 支援單已受理</h1>
      <div style="margin-top: 12px; height: 1px; background: rgba(255,255,255,0.2); width: 60%; margin-left: auto; margin-right: auto;"></div>
      <p style="color: rgba(255,255,255,0.9); margin: 12px 0 0; font-size: 14px; font-weight: 500; letter-spacing: 5px; text-indent: 5px;">您的需求已進入處理流程</p>
    </div>

    <!-- Body -->
    <div style="padding: 40px 32px;">
      <p style="color: #172B4D; font-size: 16px; font-weight: 600; margin: 0 0 16px;">
        {display_name} 您好，
      </p>
      <p style="color: #42526E; font-size: 15px; line-height: 1.6; margin: 0 0 24px;">
        您的 IT 支援需求已成功提交，IT 團隊將儘速為您處理。以下是您的需求摘要：
      </p>

      <!-- Info Card -->
      <div style="background-color: #FAFBFC; border: 1px solid #DFE1E6; border-radius: 8px; padding: 24px 0;">
        <table style="width: 100%; border-collapse: collapse;">
          <tr>
            <td style="padding: 10px 24px; color: #6B778C; font-size: 14px; font-weight: 600; width: 100px;">單號</td>
            <td style="padding: 10px 24px; color: #172B4D; font-size: 15px; font-weight: 700;">{issue_id}</td>
          </tr>
          <tr style="background-color: #ffffff;">
            <td style="padding: 10px 24px; color: #6B778C; font-size: 14px; font-weight: 600;">需求摘要</td>
            <td style="padding: 10px 24px; color: #172B4D; font-size: 15px;">{summary}</td>
          </tr>
          <tr>
            <td style="padding: 10px 24px; color: #6B778C; font-size: 14px; font-weight: 600;">分類</td>
            <td style="padding: 10px 24px; color: #172B4D; font-size: 15px;">{category}</td>
          </tr>
          <tr style="background-color: #ffffff;">
            <td style="padding: 10px 24px; color: #6B778C; font-size: 14px; font-weight: 600;">優先順序</td>
            <td style="padding: 10px 24px; color: #172B4D; font-size: 15px;">
              <span style="color: {'#DE350B' if priority == 'P1' else '#172B4D'}; font-weight: 600;">{priority}</span>
            </td>
          </tr>
        </table>
      </div>

      {link_button}

      <div style="background-color: #EBF5FB; border-left: 4px solid #0052CC; padding: 20px; border-radius: 4px; margin-top: 32px;">
        <p style="color: #0747A6; font-size: 14px; margin: 0; line-height: 1.6;">
          <strong>小提示：</strong> 如需補充資訊或附加檔案，可直接在 Teams 中將檔案傳送給 IT Bot，系統將自動為您關聯至此支援單。
        </p>
      </div>
    </div>

    <!-- Footer -->
    <div style="background-color: #F4F5F7; padding: 24px; text-align: center; border-top: 1px solid #DFE1E6;">
      <p style="color: #6B778C; font-size: 12px; margin: 0;">台灣林內-資訊課 · services@rinnai.com.tw</p>
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
            msg = MIMEMultipart("alternative")
            msg["From"] = self.smtp_user
            msg["To"] = to_email
            msg["Subject"] = subject
            
            # 轉換 body_text 中的換行為 HTML br (如果需要)
            html_content = body_text.replace("\n", "<br>")
            
            html_body = f"""\
<html>
<body style="font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #F4F5F7; padding: 40px 20px; margin: 0;">
  <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; 
              box-shadow: 0 4px 20px rgba(9, 30, 66, 0.15); overflow: hidden;">
    <!-- Header -->
    <div style="background-color: #0052CC; padding: 24px; text-align: left; border-bottom: 1px solid #DFE1E6;">
      <span style="color: #0052CC; font-size: 18px; font-weight: 700;">IT Notification</span>
    </div>
    
    <!-- Content -->
    <div style="padding: 32px;">
      <div style="color: #172B4D; font-size: 16px; line-height: 1.6;">
        {html_content}
      </div>
    </div>

    <!-- Footer -->
    <div style="background-color: #F4F5F7; padding: 20px; text-align: center; border-top: 1px solid #DFE1E6;">
      <p style="color: #6B778C; font-size: 12px; margin: 0;">台灣林內-資訊課 · 智慧助理系統</p>
    </div>
  </div>
</body>
</html>"""
            
            msg.attach(MIMEText(body_text, "plain", "utf-8"))
            msg.attach(MIMEText(html_body, "html", "utf-8"))

            import asyncio
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._send_smtp, msg, to_email)
            return True
        except Exception as e:
            logger.error("自訂 Email 通知發送失敗: %s", e)
            return False
