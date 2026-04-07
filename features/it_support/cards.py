from typing import Dict, Any, List

from botbuilder.schema import Activity, ActivityTypes, Attachment


def _adaptive_attachment(content: Dict[str, Any]) -> Attachment:
    return Attachment(content_type="application/vnd.microsoft.card.adaptive", content=content)


def build_it_issue_card(
    language: str,
    categories: List[Dict[str, str]],
    reporter_name: str,
    reporter_email: str,
) -> Activity:
    """Build an Adaptive Card for IT issue submission."""

    texts = {
        "zh": {
            "title": "提交 IT 問題／請求",
            "summary": "主旨",
            "desc": "問題描述（必填：請詳述現象、操作步驟、預期結果）",
            "placeholder": "請描述現象、操作步驟與影響",
            "category": "分類",
            "priority": "優先層級",
            "paste_hint": "提單後 10 分鐘內可直接貼上或拖曳圖片／檔案，我會自動附加到此工單。",
            "upload_options": "檔案上傳方式",
            "opt1": "1. 直接貼上或拖曳（建議）",
            "opt2": "2. 提供網路連結",
            "opt3": "3. 使用 Teams 附件功能",
            "auto_category_hint": "分類將由系統自動判斷",
            "reporter": "提報人",
            "submit": "送出",
            "auto": "（自動判斷）",
        },
        "en": {
            "title": "Submit IT Issue/Request",
            "summary": "Summary",
            "desc": "Description (required: symptoms, steps, expected result)",
            "placeholder": "Describe symptoms, reproduction steps, and impact",
            "category": "Category",
            "priority": "Priority",
            "paste_hint": "Paste or drag images/files in this chat; I'll attach them to the ticket.",
            "upload_options": "File Upload Options",
            "opt1": "1. Inline attachment (recommended)",
            "opt2": "2. Provide an internet link",
            "opt3": "3. Use Teams attachment",
            "auto_category_hint": "Category will be auto-classified",
            "reporter": "Reporter",
            "submit": "Submit",
            "auto": "(auto classified)",
        },
        "ja": {
            "title": "IT 問題・依頼の送信",
            "summary": "件名",
            "desc": "説明（必須：現象・操作手順・期待結果を記載）",
            "placeholder": "現象・操作手順・影響を記載してください",
            "category": "カテゴリ",
            "priority": "優先度",
            "paste_hint": "このチャットに画像やファイルを貼り付け／ドラッグすると、チケットに自動添付します。",
            "upload_options": "ファイルのアップロード方法",
            "opt1": "1. 直接貼り付け／ドラッグ（推奨）",
            "opt2": "2. インターネットリンクを提供",
            "opt3": "3. Teams の添付機能を利用",
            "auto_category_hint": "カテゴリはシステムが自動判定します",
            "reporter": "申請者",
            "submit": "送信",
            "auto": "（自動判定）",
        },
    }

    priority_choice_map = {
        "zh": [
            {"title": "P1 - 緊急（30 分內回應 / 3 小時內完成）", "value": "P1"},
            {"title": "P2 - 高（2 小時內回應 / 8 小時內完成）", "value": "P2"},
            {"title": "P3 - 中（1 天內回應 / 3 天內完成）", "value": "P3"},
            {"title": "P4 - 低（2 天內回應 / 5 天內完成）", "value": "P4"},
        ],
        "en": [
            {"title": "P1 - Critical (respond <30 min / resolve <3 hrs)", "value": "P1"},
            {"title": "P2 - High (respond <2 hrs / resolve <8 hrs)", "value": "P2"},
            {"title": "P3 - Medium (respond <1 day / resolve <3 days)", "value": "P3"},
            {"title": "P4 - Low (respond <2 days / resolve <5 days)", "value": "P4"},
        ],
        "ja": [
            {"title": "P1 - 緊急（30 分以内回答 / 3 時間以内解決）", "value": "P1"},
            {"title": "P2 - 高（2 時間以内回答 / 8 時間以内解決）", "value": "P2"},
            {"title": "P3 - 中（1 日以内回答 / 3 日以内解決）", "value": "P3"},
            {"title": "P4 - 低（2 日以内回答 / 5 日以内解決）", "value": "P4"},
        ],
    }

    t = texts.get(language, texts["zh"])
    priority_choices = priority_choice_map.get(language, priority_choice_map["zh"])
    category_choices = [
        {"title": c.get("label", c.get("code")), "value": c.get("code")}
        for c in categories
    ]

    card_content: Dict[str, Any] = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {"type": "TextBlock", "text": f"🛠️ {t['title']}", "weight": "Bolder", "size": "Medium"},
            {
                "type": "Input.Text",
                "id": "description",
                "label": t["desc"],
                "isMultiline": True,
                "maxLength": 10000,
                "placeholder": t.get("placeholder", t["desc"]),
                "height": "stretch",
            },
            {
                "type": "TextBlock",
                "text": t.get("auto_category_hint", t.get("auto", "")),
                "wrap": True,
                "spacing": "Small",
                "size": "Small",
                "color": "Good",
            },
            {
                "type": "Input.ChoiceSet",
                "id": "priority",
                "label": t["priority"],
                "choices": priority_choices,
                "value": "P3",
            },
            {
                "type": "TextBlock",
                "text": t["paste_hint"],
                "wrap": True,
                "spacing": "Small",
                "size": "Small",
            },
            {
                "type": "TextBlock",
                "text": f"{t['reporter']}: {reporter_name} <{reporter_email}>",
                "wrap": True,
                "spacing": "Small",
                "size": "Small",
                "color": "Accent",
            },
        ],
        "actions": [
            {"type": "Action.Submit", "title": f"✅ {t['submit']}", "data": {"action": "submitIT"}}
        ],
    }

    return Activity(type=ActivityTypes.message, attachments=[_adaptive_attachment(card_content)])


def build_send_message_card(language: str, user_choices: list) -> Activity:
    """Build an Adaptive Card for IT staff to send a message to a specific user.

    Parameters
    ----------
    language : str
        UI language code (``"zh"`` / ``"en"`` / ``"ja"``).
    user_choices : list[dict]
        Each item must have ``{"title": "單位-姓名", "value": "email"}``.
    """

    texts = {
        "zh": {
            "title": "發送訊息給使用者",
            "target": "選擇收件人",
            "message": "訊息內容",
            "message_placeholder": "請輸入要發送的訊息",
            "paste_hint": "送出後 5 分鐘內可直接貼上或拖曳圖片，我會一併轉發給對方。",
            "submit": "發送",
            "no_user": "目前沒有可發送的對象，請等待使用者與 Bot 互動後再試。",
        },
        "en": {
            "title": "Send Message to User",
            "target": "Select Recipient",
            "message": "Message",
            "message_placeholder": "Enter the message to send",
            "paste_hint": "After sending, you can paste or drag images within 5 minutes to forward them.",
            "submit": "Send",
            "no_user": "No available recipients. Please wait until users interact with the Bot.",
        },
        "ja": {
            "title": "ユーザーへメッセージ送信",
            "target": "宛先を選択",
            "message": "メッセージ",
            "message_placeholder": "送信するメッセージを入力してください",
            "paste_hint": "送信後 5 分以内に画像を貼り付け／ドラッグすると、相手に転送します。",
            "submit": "送信",
            "no_user": "送信可能な相手がいません。ユーザーが Bot と対話した後に再試行してください。",
        },
    }

    t = texts.get(language, texts["zh"])

    if not user_choices:
        return Activity(
            type=ActivityTypes.message,
            text=f"⚠️ {t['no_user']}",
        )

    card_content: Dict[str, Any] = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {"type": "TextBlock", "text": f"💬 {t['title']}", "weight": "Bolder", "size": "Medium"},
            {
                "type": "Input.ChoiceSet",
                "id": "targetUserEmail",
                "label": t["target"],
                "choices": user_choices,
                "isRequired": True,
                "style": "filtered",
            },
            {
                "type": "Input.Text",
                "id": "sendMessageText",
                "label": t["message"],
                "isMultiline": True,
                "maxLength": 2000,
                "placeholder": t["message_placeholder"],
                "height": "stretch",
                "isRequired": True,
            },
            {
                "type": "TextBlock",
                "text": t["paste_hint"],
                "wrap": True,
                "spacing": "Small",
                "size": "Small",
            },
        ],
        "actions": [
            {"type": "Action.Submit", "title": f"🚀 {t['submit']}", "data": {"action": "submitSendMessage"}}
        ],
    }

    return Activity(type=ActivityTypes.message, attachments=[_adaptive_attachment(card_content)])


def build_my_tickets_card(incomplete: List[Dict], recent_completed: List[Dict]) -> Activity:
    """Build an Adaptive Card showing user's IT tickets."""

    body: List[Dict[str, Any]] = [
        {"type": "TextBlock", "text": "📋 我的 IT 支援單", "weight": "Bolder", "size": "Medium"},
    ]

    # ── 未完成 ──
    if incomplete:
        body.append({
            "type": "TextBlock",
            "text": f"🔴 未完成（{len(incomplete)} 筆）",
            "weight": "Bolder", "size": "Small", "spacing": "Medium",
            "color": "Attention",
        })
        for t in incomplete:
            facts = [
                {"title": "單號", "value": t["issue_id"]},
                {"title": "分類", "value": t["category"] or "—"},
                {"title": "優先序", "value": t["priority"] or "—"},
                {"title": "提交日期", "value": t["created_at"]},
            ]
            if t.get("description"):
                facts.append({"title": "需求摘要", "value": t["description"]})
            body.append({
                "type": "Container",
                "style": "emphasis",
                "spacing": "Small",
                "items": [{"type": "FactSet", "facts": facts}],
                "separator": True,
            })
    else:
        body.append({
            "type": "TextBlock",
            "text": "✅ 沒有未完成的支援單",
            "spacing": "Medium", "color": "Good",
        })

    # ── 最近已完成 ──
    if recent_completed:
        body.append({
            "type": "TextBlock",
            "text": f"🟢 最近已完成（前 {len(recent_completed)} 筆）",
            "weight": "Bolder", "size": "Small", "spacing": "Large",
            "color": "Good",
        })
        for t in recent_completed:
            facts = [
                {"title": "單號", "value": t["issue_id"]},
                {"title": "分類", "value": t["category"] or "—"},
                {"title": "提交日期", "value": t["created_at"]},
            ]
            if t.get("description"):
                facts.append({"title": "需求摘要", "value": t["description"]})
            body.append({
                "type": "Container",
                "spacing": "Small",
                "items": [{"type": "FactSet", "facts": facts}],
                "separator": True,
            })

    body.append({
        "type": "TextBlock",
        "text": "輸入 @it 提交新的支援需求",
        "size": "Small", "spacing": "Medium", "isSubtle": True,
    })

    card_content: Dict[str, Any] = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": body,
    }

    return Activity(type=ActivityTypes.message, attachments=[_adaptive_attachment(card_content)])


def build_broadcast_card(language: str) -> Activity:
    """Build an Adaptive Card for sending broadcast messages."""

    texts = {
        "zh": {
            "title": "發送廣播推播",
            "target": "收件人 Email (全發送請輸入 `all`，多筆請用分號分隔)",
            "target_placeholder": "例如：all 或 a@rinnai.com.tw;b@rinnai.com.tw",
            "message": "推播訊息",
            "message_placeholder": "請輸入要發送給大家的訊息",
            "submit": "發送推播",
        },
        "en": {
            "title": "Send Broadcast Message",
            "target": "Target Email (Enter `all` to broadcast, or use semicolons for multiple)",
            "target_placeholder": "e.g., all or a@rinnai.com.tw;b@rinnai.com.tw",
            "message": "Broadcast Message",
            "message_placeholder": "Enter the message to broadcast",
            "submit": "Send",
        },
        "ja": {
            "title": "ブロードキャスト送信",
            "target": "宛先 Email (全員送信は `all`、複数はセミコロンで区切る)",
            "target_placeholder": "例：all または a@rinnai.com.tw;b@rinnai.com.tw",
            "message": "メッセージ",
            "message_placeholder": "送信するメッセージを入力してください",
            "submit": "送信",
        },
    }

    t = texts.get(language, texts["zh"])

    card_content: Dict[str, Any] = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {"type": "TextBlock", "text": f"📢 {t['title']}", "weight": "Bolder", "size": "Medium"},
            {
                "type": "Input.Text",
                "id": "targetEmails",
                "label": t["target"],
                "placeholder": t["target_placeholder"],
                "value": "all",
                "maxLength": 1000,
            },
            {
                "type": "Input.Text",
                "id": "broadcastMessage",
                "label": t["message"],
                "isMultiline": True,
                "maxLength": 2000,
                "placeholder": t["message_placeholder"],
                "height": "stretch",
            },
        ],
        "actions": [
            {"type": "Action.Submit", "title": f"🚀 {t['submit']}", "data": {"action": "submitBroadcast"}}
        ],
    }

    return Activity(type=ActivityTypes.message, attachments=[_adaptive_attachment(card_content)])

def build_itt_issue_card(
    language: str,
    categories: List[Dict[str, str]],
    reporter_name: str,
    reporter_email: str,
) -> Activity:
    """Build an Adaptive Card for IT issue submission on behalf of another user (IT Team proxy)."""

    texts = {
        "zh": {
            "title": "提交 IT 問題／請求（代提單）",
            "summary": "主旨",
            "desc": "問題描述（必填：請詳述現象、操作步驟、預期結果）",
            "placeholder": "請描述現象、操作步驟與影響",
            "category": "分類",
            "priority": "優先層級",
            "paste_hint": "提單後 10 分鐘內可直接貼上或拖曳圖片／檔案，我會自動附加到此工單。",
            "auto_category_hint": "分類將由系統自動判斷",
            "requester_email": "提出人 Email（完成後將通知此人）",
            "requester_placeholder": "例如：someone@rinnai.com.tw",
            "reporter": "代理提報人",
            "submit": "送出",
            "auto": "（自動判斷）",
        },
        "en": {
            "title": "Submit IT Issue/Request (Proxy)",
            "summary": "Summary",
            "desc": "Description (required: symptoms, steps, expected result)",
            "placeholder": "Describe symptoms, reproduction steps, and impact",
            "category": "Category",
            "priority": "Priority",
            "paste_hint": "Paste or drag images/files in this chat; I'll attach them to the ticket.",
            "auto_category_hint": "Category will be auto-classified",
            "requester_email": "Requester Email (will be notified on completion)",
            "requester_placeholder": "e.g., someone@rinnai.com.tw",
            "reporter": "Proxy Reporter",
            "submit": "Submit",
            "auto": "(auto classified)",
        },
        "ja": {
            "title": "IT 問題・依頼の送信（代理）",
            "summary": "件名",
            "desc": "説明（必須：現象・操作手順・期待結果を記載）",
            "placeholder": "現象・操作手順・影響を記載してください",
            "category": "カテゴリ",
            "priority": "優先度",
            "paste_hint": "このチャットに画像やファイルを貼り付け／ドラッグすると、チケットに自動添付します。",
            "auto_category_hint": "カテゴリはシステムが自動判定します",
            "requester_email": "依頼者メール（完了時に通知されます）",
            "requester_placeholder": "例：someone@rinnai.com.tw",
            "reporter": "代理申請者",
            "submit": "送信",
            "auto": "（自動判定）",
        },
    }

    priority_choice_map = {
        "zh": [
            {"title": "P1 - 緊急（30 分內回應 / 3 小時內完成）", "value": "P1"},
            {"title": "P2 - 高（2 小時內回應 / 8 小時內完成）", "value": "P2"},
            {"title": "P3 - 中（1 天內回應 / 3 天內完成）", "value": "P3"},
            {"title": "P4 - 低（2 天內回應 / 5 天內完成）", "value": "P4"},
        ],
        "en": [
            {"title": "P1 - Critical (respond <30 min / resolve <3 hrs)", "value": "P1"},
            {"title": "P2 - High (respond <2 hrs / resolve <8 hrs)", "value": "P2"},
            {"title": "P3 - Medium (respond <1 day / resolve <3 days)", "value": "P3"},
            {"title": "P4 - Low (respond <2 days / resolve <5 days)", "value": "P4"},
        ],
        "ja": [
            {"title": "P1 - 緊急（30 分以内回答 / 3 時間以内解決）", "value": "P1"},
            {"title": "P2 - 高（2 時間以内回答 / 8 時間以内解決）", "value": "P2"},
            {"title": "P3 - 中（1 日以内回答 / 3 日以内解決）", "value": "P3"},
            {"title": "P4 - 低（2 日以内回答 / 5 日以内解決）", "value": "P4"},
        ],
    }

    t = texts.get(language, texts["zh"])
    priority_choices = priority_choice_map.get(language, priority_choice_map["zh"])

    card_content: Dict[str, Any] = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {"type": "TextBlock", "text": f"🛠️ {t['title']}", "weight": "Bolder", "size": "Medium"},
            {
                "type": "Input.Text",
                "id": "requesterEmail",
                "label": t["requester_email"],
                "placeholder": t["requester_placeholder"],
                "maxLength": 200,
                "style": "Email",
            },
            {
                "type": "Input.Text",
                "id": "description",
                "label": t["desc"],
                "isMultiline": True,
                "maxLength": 10000,
                "placeholder": t.get("placeholder", t["desc"]),
                "height": "stretch",
            },
            {
                "type": "TextBlock",
                "text": t.get("auto_category_hint", t.get("auto", "")),
                "wrap": True,
                "spacing": "Small",
                "size": "Small",
                "color": "Good",
            },
            {
                "type": "Input.ChoiceSet",
                "id": "priority",
                "label": t["priority"],
                "choices": priority_choices,
                "value": "P3",
            },
            {
                "type": "TextBlock",
                "text": t["paste_hint"],
                "wrap": True,
                "spacing": "Small",
                "size": "Small",
            },
            {
                "type": "TextBlock",
                "text": f"{t['reporter']}: {reporter_name} <{reporter_email}>",
                "wrap": True,
                "spacing": "Small",
                "size": "Small",
                "color": "Accent",
            },
        ],
        "actions": [
            {"type": "Action.Submit", "title": f"✅ {t['submit']}", "data": {"action": "submitITT"}}
        ],
    }

    return Activity(type=ActivityTypes.message, attachments=[_adaptive_attachment(card_content)])


def build_broadcast_card(language: str) -> Activity:
    """Build an Adaptive Card for sending broadcast messages."""

    texts = {
        "zh": {
            "title": "發送廣播推播",
            "target": "收件人 Email (全發送請輸入 `all`，多筆請用分號分隔)",
            "target_placeholder": "例如：all 或 a@rinnai.com.tw;b@rinnai.com.tw",
            "message": "推播訊息",
            "message_placeholder": "請輸入要發送給大家的訊息",
            "submit": "發送推播",
        },
        "en": {
            "title": "Send Broadcast Message",
            "target": "Target Email (Enter `all` to broadcast, or use semicolons for multiple)",
            "target_placeholder": "e.g., all or a@rinnai.com.tw;b@rinnai.com.tw",
            "message": "Broadcast Message",
            "message_placeholder": "Enter the message to broadcast",
            "submit": "Send",
        },
        "ja": {
            "title": "ブロードキャスト送信",
            "target": "宛先 Email (全員送信は `all`、複数はセミコロンで区切る)",
            "target_placeholder": "例：all または a@rinnai.com.tw;b@rinnai.com.tw",
            "message": "メッセージ",
            "message_placeholder": "送信するメッセージを入力してください",
            "submit": "送信",
        },
    }

    t = texts.get(language, texts["zh"])

    card_content: Dict[str, Any] = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {"type": "TextBlock", "text": f"📢 {t['title']}", "weight": "Bolder", "size": "Medium"},
            {
                "type": "Input.Text",
                "id": "targetEmails",
                "label": t["target"],
                "placeholder": t["target_placeholder"],
                "value": "all",
                "maxLength": 1000,
            },
            {
                "type": "Input.Text",
                "id": "broadcastMessage",
                "label": t["message"],
                "isMultiline": True,
                "maxLength": 2000,
                "placeholder": t["message_placeholder"],
                "height": "stretch",
            },
        ],
        "actions": [
            {"type": "Action.Submit", "title": f"🚀 {t['submit']}", "data": {"action": "submitBroadcast"}}
        ],
    }

    return Activity(type=ActivityTypes.message, attachments=[_adaptive_attachment(card_content)])
