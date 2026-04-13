"""
Email 通知模組
透過 SMTP 發送 IT 單完成通知郵件
"""
import os
import re
import html as html_mod
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

logger = logging.getLogger(__name__)

# ── 共用樣式常數 ──────────────────────────────────────────────
_FONT = "'Segoe UI', Helvetica, Arial, sans-serif"
_CLR_NAVY = "#1B2A4A"
_CLR_GREEN = "#10B981"
_CLR_BLUE = "#3B82F6"
_CLR_BODY = "#374151"
_CLR_MUTED = "#9CA3AF"
_CLR_LABEL = "#6B7280"
_CLR_CARD_BG = "#F9FAFB"
_CLR_BORDER = "#E5E7EB"
_CLR_BORDER_LIGHT = "#F3F4F6"


def _section_header(title: str) -> str:
    """卡片區塊的灰色標題列"""
    return (
        f'<tr><td style="background-color: {_CLR_CARD_BG}; padding: 16px 20px; '
        f'border-bottom: 1px solid {_CLR_BORDER};">'
        f'<span style="font-family: {_FONT}; color: {_CLR_LABEL}; font-size: 11px; '
        f'font-weight: 700; letter-spacing: 2px; text-transform: uppercase;">{title}</span>'
        f'</td></tr>'
    )


def _info_row(label: str, value: str, is_last: bool = False, value_style: str = "") -> str:
    """資訊表格中的單列"""
    border = "" if is_last else f"border-bottom: 1px solid {_CLR_BORDER_LIGHT};"
    v_style = value_style or f"color: {_CLR_BODY}; font-size: 14px;"
    return (
        f'<tr>'
        f'<td style="padding: 14px 20px; {border} width: 100px;">'
        f'<span style="font-family: {_FONT}; color: {_CLR_MUTED}; font-size: 13px;">{label}</span></td>'
        f'<td style="padding: 14px 20px; {border}">'
        f'<span style="font-family: {_FONT}; {v_style}">{value}</span></td>'
        f'</tr>'
    )


def _wrap_email(header_html: str, body_html: str) -> str:
    """將 header + body 包進完整 email 骨架（table-based layout for Outlook）"""
    return f"""\
<html>
<body style="margin: 0; padding: 0; -webkit-text-size-adjust: 100%;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background-color: #EAEEF3; padding: 32px 0;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0"
       style="background-color: #ffffff; border-radius: 16px; overflow: hidden;
              box-shadow: 0 2px 24px rgba(0,0,0,0.08);">

  {header_html}

  {body_html}

  <!-- FOOTER -->
  <tr>
    <td style="background-color: {_CLR_CARD_BG}; border-top: 1px solid {_CLR_BORDER}; padding: 24px 40px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td>
            <p style="font-family: {_FONT}; color: {_CLR_MUTED}; font-size: 11px; margin: 0; line-height: 1.6;">
              此為系統自動發送郵件，請勿直接回覆。</p>
            <p style="font-family: {_FONT}; color: {_CLR_MUTED}; font-size: 11px; margin: 6px 0 0;">
              📎 TR GPT 支援上傳：圖片（PNG/JPG/BMP/GIF/WebP）、PDF、Word(.docx)、Excel(.xlsx/.xls)、PowerPoint(.pptx)、純文字檔</p>
            <p style="font-family: {_FONT}; color: {_CLR_MUTED}; font-size: 11px; margin: 6px 0 0;">
              台灣林內 &middot; 資訊課 &middot; TR GPT</p>
          </td>
          <td align="right" valign="top">
            <span style="font-family: {_FONT}; color: #D1D5DB; font-size: 10px; letter-spacing: 1px;">RINNAI</span>
          </td>
        </tr>
      </table>
    </td>
  </tr>

</table>
</td></tr>
</table>
</body>
</html>"""


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

    # ── 完成通知 ──────────────────────────────────────────────────

    def _build_completion_email(
        self,
        to_email: str,
        issue_id: str,
        task_name: str,
        permalink_url: str = "",
        comments: str = "",
        description: str = "",
        images: Optional[list] = None,
    ) -> MIMEMultipart:
        """建立任務完成通知郵件。
        images: list of {"filename": str, "data": bytes, "content_type": str}
        """
        msg = MIMEMultipart("related")
        msg["From"] = self.smtp_user
        msg["To"] = to_email
        msg["Subject"] = f"IT 單 {issue_id} 已處理完成"
        alt_part = MIMEMultipart("alternative")
        images = images or []

        # ── 純文字版本 ──
        text_body = (
            f"您好，\n\n"
            f"您提交的 IT 支援需求已由服務台工程師處理完成：\n\n"
            f"  單號：{issue_id}\n"
            f"  摘要：{task_name}\n"
        )
        if description:
            text_body += f"\n您當初提交的需求內容：\n{description}\n"
        if comments:
            text_body += f"\n處理評論：\n{comments}\n"
        if permalink_url:
            text_body += f"  連結：{permalink_url}\n"
        text_body += (
            f"\n如有其他問題，請在 Teams 中使用 @it 再次提單。\n\n"
            f"台灣林內-TR GPT"
        )

        # ── HTML header ──
        header_html = f"""
  <tr>
    <td style="background-color: {_CLR_NAVY}; padding: 0;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td style="padding: 36px 40px 32px;">
            <table role="presentation" cellpadding="0" cellspacing="0"><tr>
              <td style="width: 36px; height: 36px; background-color: {_CLR_GREEN};
                         border-radius: 10px; text-align: center; vertical-align: middle;
                         font-size: 18px; color: #ffffff;">&#10003;</td>
              <td style="padding-left: 14px;">
                <span style="font-family: {_FONT}; color: #ffffff; font-size: 13px;
                             font-weight: 600; letter-spacing: 3px; text-transform: uppercase;
                             opacity: 0.7;">RINNAI IT</span></td>
            </tr></table>
          </td>
        </tr>
        <tr>
          <td style="padding: 0 40px 36px;">
            <h1 style="font-family: {_FONT}; color: #ffffff; margin: 0;
                       font-size: 28px; font-weight: 700; line-height: 1.2;">
              您的支援需求<br>已處理完成</h1>
            <div style="margin-top: 16px; display: inline-block; background-color: {_CLR_GREEN};
                        border-radius: 20px; padding: 6px 16px;">
              <span style="font-family: {_FONT}; color: #ffffff; font-size: 12px;
                           font-weight: 700; letter-spacing: 1px;">已完成</span></div>
          </td>
        </tr>
      </table>
    </td>
  </tr>"""

        # ── HTML body sections ──
        body_parts = []

        # 支援單資訊
        body_parts.append(f"""
  <tr><td style="padding: 40px 40px 16px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="border: 1px solid {_CLR_BORDER}; border-radius: 12px; overflow: hidden;">
      {_section_header('支援單資訊')}
      <tr><td style="padding: 0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
          {_info_row('單號', issue_id, value_style=f'color: {_CLR_NAVY}; font-size: 15px; font-weight: 700;')}
          {_info_row('摘要', html_mod.escape(task_name), is_last=True)}
        </table>
      </td></tr>
    </table>
  </td></tr>""")

        # 需求內容
        if description:
            desc_html = html_mod.escape(description).replace("\n", "<br>")
            body_parts.append(f"""
  <tr><td style="padding: 16px 40px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="border: 1px solid {_CLR_BORDER}; border-radius: 12px; overflow: hidden;">
      {_section_header('您提交的需求內容')}
      <tr><td style="padding: 20px;">
        <p style="font-family: {_FONT}; color: #4B5563; font-size: 14px;
                  line-height: 1.7; margin: 0; white-space: pre-wrap;">{desc_html}</p>
      </td></tr>
    </table>
  </td></tr>""")

        # 評論
        if comments:
            comment_rows = self._build_comment_rows(comments)
            if comment_rows:
                body_parts.append(f"""
  <tr><td style="padding: 16px 40px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="border: 1px solid {_CLR_BORDER}; border-radius: 12px; overflow: hidden;">
      {_section_header('處理評論')}
      <tr><td style="padding: 0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
          {comment_rows}
        </table>
      </td></tr>
    </table>
  </td></tr>""")

        # 附件圖片
        if images:
            img_items = ""
            for idx, img in enumerate(images):
                cid = f"att_img_{idx}"
                fname = html_mod.escape(img.get("filename", f"image_{idx}"))
                img_items += (
                    f'<tr><td style="padding: 12px 20px; border-bottom: 1px solid {_CLR_BORDER_LIGHT};">'
                    f'<p style="font-family: {_FONT}; color: {_CLR_MUTED}; font-size: 12px; margin: 0 0 8px;">{fname}</p>'
                    f'<img src="cid:{cid}" style="max-width: 100%; border-radius: 8px; display: block;" alt="{fname}">'
                    f'</td></tr>'
                )
            body_parts.append(f"""
  <tr><td style="padding: 16px 40px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="border: 1px solid {_CLR_BORDER}; border-radius: 12px; overflow: hidden;">
      {_section_header('附件圖片')}
      <tr><td style="padding: 0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
          {img_items}
        </table>
      </td></tr>
    </table>
  </td></tr>""")

        # 提示
        body_parts.append(f"""
  <tr><td style="padding: 24px 40px 40px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
      <td style="background-color: #F0FDF4; border-radius: 10px; padding: 20px;
                 border: 1px solid #BBF7D0;">
        <p style="font-family: {_FONT}; color: #166534; font-size: 13px; margin: 0; line-height: 1.6;">
          <strong>需要進一步協助？</strong><br>
          如問題尚未解決或有後續需求，請在 Teams 中輸入
          <code style="background-color: #DCFCE7; padding: 2px 6px; border-radius: 4px;
                       font-size: 12px; color: #15803D;">@it</code> 重新提單。</p>
      </td>
    </tr></table>
  </td></tr>""")

        html_body = _wrap_email(header_html, "\n".join(body_parts))
        alt_part.attach(MIMEText(text_body, "plain", "utf-8"))
        alt_part.attach(MIMEText(html_body, "html", "utf-8"))
        msg.attach(alt_part)

        # 內嵌圖片為 cid 附件
        if images:
            from email.mime.image import MIMEImage
            for idx, img in enumerate(images):
                cid = f"att_img_{idx}"
                ct = img.get("content_type", "image/png")
                maintype, subtype = ct.split("/", 1) if "/" in ct else ("image", "png")
                mime_img = MIMEImage(img["data"], _subtype=subtype)
                mime_img.add_header("Content-ID", f"<{cid}>")
                mime_img.add_header("Content-Disposition", "inline", filename=img.get("filename", f"image_{idx}"))
                msg.attach(mime_img)

        return msg

    def _build_comment_rows(self, comments: str) -> str:
        """將 markdown 格式評論轉為 HTML 表格列（含頭像）"""
        rows = []
        lines = [ln.strip() for ln in comments.strip().split("\n") if ln.strip()]
        for i, line in enumerate(lines):
            if line.startswith("- "):
                line = line[2:]
            # 提取作者名
            m = re.match(r'\*\*(.+?)\*\*:\s*(.*)', line)
            if m:
                author = m.group(1)
                text = html_mod.escape(m.group(2))
                initials = author[0] if author else "ℹ"
            else:
                line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
                author = ""
                text = line
                initials = "ℹ"

            is_last = (i == len(lines) - 1)
            border = "" if is_last else f"border-bottom: 1px solid {_CLR_BORDER_LIGHT};"
            rows.append(f"""
          <tr><td style="padding: 16px 20px; {border}">
            <table role="presentation" cellpadding="0" cellspacing="0"><tr>
              <td style="width: 32px; height: 32px; background-color: #DBEAFE;
                         border-radius: 50%; text-align: center; vertical-align: middle;">
                <span style="font-family: {_FONT}; color: #2563EB; font-size: 13px;
                             font-weight: 700;">{html_mod.escape(initials)}</span></td>
              <td style="padding-left: 12px; vertical-align: top;">
                {"<span style=" + '"' + f"font-family: {_FONT}; color: #1F2937; font-size: 13px; font-weight: 600;" + '"' + f">{html_mod.escape(author)}</span>" if author else ""}
                <p style="font-family: {_FONT}; color: #4B5563; font-size: 14px;
                          line-height: 1.6; margin: {'4px' if author else '0'} 0 0;">{text}</p>
              </td>
            </tr></table>
          </td></tr>""")
        return "\n".join(rows)

    async def send_completion_notification(
        self,
        to_email: str,
        issue_id: str,
        task_name: str,
        permalink_url: str = "",
        comments: str = "",
        description: str = "",
        images: Optional[list] = None,
    ) -> bool:
        """發送任務完成通知郵件。回傳 True 表示成功。
        images: list of {"filename": str, "data": bytes, "content_type": str}
        """
        if not self.smtp_user or not self.smtp_password:
            logger.warning("SMTP 未設定，跳過 Email 通知")
            return False

        try:
            msg = self._build_completion_email(to_email, issue_id, task_name, permalink_url, comments, description, images)

            import asyncio
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._send_smtp, msg, to_email)

            logger.info("Email 通知已發送至 %s (單號: %s)", to_email, issue_id)
            return True
        except Exception as e:
            logger.error("Email 通知發送失敗: %s", e)
            return False

    def _send_smtp(self, msg: MIMEMultipart, to_email: str, cc_emails: Optional[list] = None) -> None:
        """同步 SMTP 發送（在 executor 中執行）"""
        logger.info("SMTP connecting: %s:%s", self.smtp_host, self.smtp_port)
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as server:
                server.set_debuglevel(0)
                server.ehlo()
                server.starttls()
                server.ehlo()
                logger.info("SMTP login: %s", self.smtp_user)
                server.login(self.smtp_user, self.smtp_password)
                recipients = [to_email]
                if cc_emails:
                    recipients.extend(cc_emails)
                logger.info("SMTP send: %s -> %s (CC: %s)", self.smtp_user, to_email, cc_emails or "none")
                server.sendmail(self.smtp_user, recipients, msg.as_string())
                logger.info("SMTP send complete")
        except Exception as e:
            logger.error("SMTP error: %s: %s", type(e).__name__, e)
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
        description: str = "",
    ) -> MIMEMultipart:
        """建立提單確認通知郵件"""
        msg = MIMEMultipart("alternative")
        msg["From"] = self.smtp_user
        msg["To"] = to_email
        msg["Subject"] = f"IT 支援單已受理 — {issue_id}"

        display_name = reporter_name or to_email.split("@")[0]
        priority_color = "#DC2626" if priority in ("P1", "P2") else _CLR_BODY

        # ── 純文字版本 ──
        text_body = (
            f"{display_name} 您好，\n\n"
            f"您的 IT 支援需求已成功提交，IT 團隊將儘速為您處理。\n\n"
            f"  單號：{issue_id}\n"
            f"  需求摘要：{summary}\n"
            f"  分類：{category}\n"
            f"  優先順序：{priority}\n"
            f"  提交時間：{created_at}\n"
        )
        if description:
            text_body += f"\n您提交的需求內容：\n{description}\n"
        if permalink_url:
            text_body += f"  Asana 連結：{permalink_url}\n"
        text_body += (
            f"\n如需補充資訊或附件，請在 Teams 中直接傳送檔案給 Bot。\n"
            f"處理完成後，系統會再次通知您。\n\n"
            f"台灣林內-TR GPT\n"
            f"services@rinnai.com.tw"
        )

        # ── HTML header ──
        header_html = f"""
  <tr>
    <td style="background-color: {_CLR_NAVY}; padding: 0;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td style="padding: 36px 40px 32px;">
            <table role="presentation" cellpadding="0" cellspacing="0"><tr>
              <td style="width: 36px; height: 36px; background-color: {_CLR_BLUE};
                         border-radius: 10px; text-align: center; vertical-align: middle;
                         font-size: 16px; color: #ffffff;">&#9998;</td>
              <td style="padding-left: 14px;">
                <span style="font-family: {_FONT}; color: #ffffff; font-size: 13px;
                             font-weight: 600; letter-spacing: 3px; text-transform: uppercase;
                             opacity: 0.7;">RINNAI IT</span></td>
            </tr></table>
          </td>
        </tr>
        <tr>
          <td style="padding: 0 40px 36px;">
            <h1 style="font-family: {_FONT}; color: #ffffff; margin: 0;
                       font-size: 28px; font-weight: 700; line-height: 1.2;">
              IT 支援單已受理</h1>
            <p style="font-family: {_FONT}; color: rgba(255,255,255,0.65); margin: 12px 0 0;
                      font-size: 15px; line-height: 1.5;">
              您的需求已進入處理流程，IT 團隊將儘速為您處理。</p>
            <div style="margin-top: 16px; display: inline-block; background-color: {_CLR_BLUE};
                        border-radius: 20px; padding: 6px 16px;">
              <span style="font-family: {_FONT}; color: #ffffff; font-size: 12px;
                           font-weight: 700; letter-spacing: 1px;">處理中</span></div>
          </td>
        </tr>
      </table>
    </td>
  </tr>"""

        # ── HTML body ──
        body_parts = []

        # 問候
        body_parts.append(f"""
  <tr><td style="padding: 36px 40px 0;">
    <p style="font-family: {_FONT}; color: #1F2937; font-size: 16px; font-weight: 600; margin: 0;">
      {html_mod.escape(display_name)} 您好，</p>
  </td></tr>""")

        # 資訊卡
        body_parts.append(f"""
  <tr><td style="padding: 24px 40px 16px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="border: 1px solid {_CLR_BORDER}; border-radius: 12px; overflow: hidden;">
      {_section_header('支援單資訊')}
      <tr><td style="padding: 0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
          {_info_row('單號', issue_id, value_style=f'color: {_CLR_NAVY}; font-size: 15px; font-weight: 700;')}
          {_info_row('摘要', html_mod.escape(summary))}
          {_info_row('分類', html_mod.escape(category))}
          {_info_row('優先序', priority, value_style=f'color: {priority_color}; font-size: 14px; font-weight: 700;')}
          {_info_row('提交時間', html_mod.escape(created_at), is_last=True)}
        </table>
      </td></tr>
    </table>
  </td></tr>""")

        # 需求內容
        if description:
            desc_html = html_mod.escape(description).replace("\n", "<br>")
            body_parts.append(f"""
  <tr><td style="padding: 0 40px 16px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="border: 1px solid {_CLR_BORDER}; border-radius: 12px; overflow: hidden;">
      {_section_header('您提交的需求內容')}
      <tr><td style="padding: 20px;">
        <p style="font-family: {_FONT}; color: #4B5563; font-size: 14px;
                  line-height: 1.7; margin: 0; white-space: pre-wrap;">{desc_html}</p>
      </td></tr>
    </table>
  </td></tr>""")

        # 按鈕
        if permalink_url:
            body_parts.append(f"""
  <tr><td style="padding: 16px 40px 8px;" align="center">
    <table role="presentation" cellpadding="0" cellspacing="0"><tr>
      <td style="background-color: {_CLR_NAVY}; border-radius: 10px;">
        <a href="{permalink_url}" style="display: inline-block; padding: 14px 36px;
           font-family: {_FONT}; color: #ffffff; font-size: 14px; font-weight: 600;
           text-decoration: none; letter-spacing: 0.5px;">進入任務中心 &rarr;</a>
      </td>
    </tr></table>
  </td></tr>""")

        # 提示
        body_parts.append(f"""
  <tr><td style="padding: 24px 40px 40px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
      <td style="background-color: #EFF6FF; border-radius: 10px; padding: 20px;
                 border: 1px solid #BFDBFE;">
        <p style="font-family: {_FONT}; color: #1E40AF; font-size: 13px; margin: 0; line-height: 1.6;">
          <strong>小提示</strong><br>
          如需補充資訊或附加檔案，可直接在 Teams 中將檔案傳送給 IT Bot，系統將自動為您關聯至此支援單。
          處理完成後，系統會再次通知您。</p>
      </td>
    </tr></table>
  </td></tr>""")

        html_body = _wrap_email(header_html, "\n".join(body_parts))
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
        cc_email: str = "",
        description: str = "",
    ) -> bool:
        """發送提單確認通知郵件。可選 cc_email 用於 @itt 代提單時 CC 給提出人。回傳 True 表示成功。"""
        if not self.smtp_user or not self.smtp_password:
            logger.warning("SMTP 未設定，跳過提單確認 Email")
            return False

        try:
            msg = self._build_submission_email(
                to_email, issue_id, summary, category, priority,
                created_at, permalink_url, reporter_name, description,
            )

            cc_list = []
            if cc_email and cc_email.lower() != to_email.lower():
                msg["Cc"] = cc_email
                cc_list = [cc_email]

            import asyncio
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._send_smtp, msg, to_email, cc_list)

            cc_log = f" (CC: {cc_email})" if cc_email else ""
            logger.info("提單確認 Email 已發送至 %s%s (單號: %s)", to_email, cc_log, issue_id)
            return True
        except Exception as e:
            logger.error("提單確認 Email 發送失敗: %s", e)
            return False

    # ── 自訂通知 ──────────────────────────────────────────────────

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

            html_content = html_mod.escape(body_text).replace("\n", "<br>")

            header_html = f"""
  <tr>
    <td style="background-color: {_CLR_NAVY}; padding: 0;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td style="padding: 36px 40px;">
            <table role="presentation" cellpadding="0" cellspacing="0"><tr>
              <td style="width: 36px; height: 36px; background-color: #8B5CF6;
                         border-radius: 10px; text-align: center; vertical-align: middle;
                         font-size: 16px; color: #ffffff;">&#9993;</td>
              <td style="padding-left: 14px;">
                <span style="font-family: {_FONT}; color: #ffffff; font-size: 13px;
                             font-weight: 600; letter-spacing: 3px; text-transform: uppercase;
                             opacity: 0.7;">RINNAI IT</span></td>
            </tr></table>
          </td>
        </tr>
      </table>
    </td>
  </tr>"""

            body_html = f"""
  <tr><td style="padding: 40px;">
    <div style="font-family: {_FONT}; color: {_CLR_BODY}; font-size: 15px; line-height: 1.7;">
      {html_content}
    </div>
  </td></tr>"""

            full_html = _wrap_email(header_html, body_html)
            msg.attach(MIMEText(body_text, "plain", "utf-8"))
            msg.attach(MIMEText(full_html, "html", "utf-8"))

            import asyncio
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._send_smtp, msg, to_email)
            return True
        except Exception as e:
            logger.error("自訂 Email 通知發送失敗: %s", e)
            return False
