"""
全域嚴重錯誤郵件通知
只在啟動失敗、未捕獲例外等嚴重情況觸發，避免信箱爆量。
"""

import os
import logging
import smtplib
import traceback
import time
from email.mime.text import MIMEText
from datetime import datetime

logger = logging.getLogger(__name__)

# 防止短時間內重複寄信（同一錯誤 10 分鐘內只寄一次）
_last_sent: dict[str, float] = {}
_COOLDOWN_SECONDS = 600  # 10 分鐘


def notify_critical_error(
    subject_hint: str,
    error: Exception,
    context: str = "",
) -> None:
    """寄送嚴重錯誤通知信。

    Args:
        subject_hint: 錯誤摘要（例如 "應用程式啟動失敗"）
        error: 例外物件
        context: 額外上下文資訊
    """
    recipient = os.getenv("ALERT_EMAIL", "").strip()
    smtp_host = os.getenv("SMTP_HOST", "smtp.office365.com")
    smtp_port = int(os.getenv("SMTP_PORT", "25"))
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "").strip()

    if not recipient or not smtp_user:
        logger.warning("ALERT_EMAIL 或 SMTP_USER 未設定，無法寄送錯誤通知")
        return

    # 冷卻機制：同樣的錯誤訊息在冷卻期內不重複寄
    error_key = f"{subject_hint}:{type(error).__name__}:{str(error)[:100]}"
    now = time.time()
    if error_key in _last_sent and (now - _last_sent[error_key]) < _COOLDOWN_SECONDS:
        logger.debug("錯誤通知冷卻中，略過: %s", error_key)
        return

    try:
        tb = traceback.format_exception(type(error), error, error.__traceback__)
        tb_text = "".join(tb)

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        hostname = os.getenv("WEBSITE_HOSTNAME", os.getenv("HOSTNAME", "unknown"))

        body = f"""TR GPT 嚴重錯誤通知
========================================
時間：{timestamp}
主機：{hostname}
錯誤摘要：{subject_hint}

{f"上下文：{context}" if context else ""}

錯誤類型：{type(error).__name__}
錯誤訊息：{str(error)}

完整堆疊追蹤：
{tb_text}
========================================
此為自動通知，請勿直接回覆。
"""

        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = f"[TR GPT Alert] {subject_hint}"
        msg["From"] = smtp_user
        msg["To"] = recipient

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            if smtp_port != 25:
                server.starttls()
            if smtp_password:
                server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, [recipient], msg.as_string())

        _last_sent[error_key] = now
        logger.info("已寄送錯誤通知至 %s: %s", recipient, subject_hint)

    except Exception as mail_err:
        logger.error("寄送錯誤通知郵件失敗: %s", mail_err)
