from typing import Dict, Any, List, Optional
from botbuilder.schema import Activity, ActivityTypes, Attachment


def _adaptive_attachment(content: Dict[str, Any]) -> Attachment:
    return Attachment(content_type="application/vnd.microsoft.card.adaptive", content=content)


def build_it_issue_card(language: str,
                        categories: List[Dict[str, str]],
                        reporter_name: str,
                        reporter_email: str) -> Activity:
    """
    Build an Adaptive Card for IT issue submission.
    Fields: summary, description, category, priority, reporter (readonly), submit.
    """
    texts = {
        "zh": {
            "title": "提交 IT 需求/問題",
            "summary": "問題標題",
            "desc": "需求/問題說明（必填，請詳述症狀、步驟、預期）",
            "category": "問題分類",
            "priority": "優先順序",
            "paste_hint": "可直接在此對話後貼上或拖曳圖片/檔案，我會自動附加到此單。",
            "upload_options": "上傳檔案方式",
            "opt1": "1. 內嵌附件（貼上圖片）",
            "opt2": "2. 網路附件（提供網址）",
            "opt3": "3. 已上傳附件（Teams 附件）",
            "auto_category_hint": "分類將由系統自動判斷",
            "reporter": "提出人",
            "submit": "提交",
            "auto": "（可自動判斷）"
        },
        "en": {
            "title": "Submit IT Issue/Request",
            "summary": "Summary",
            "desc": "Description (required: symptoms, steps, expectation)",
            "category": "Category",
            "priority": "Priority",
            "paste_hint": "Paste or drag images/files in this chat; I'll attach them to the ticket.",
            "upload_options": "File Upload Options",
            "opt1": "1. Inline Attachment",
            "opt2": "2. Internet Attachment",
            "opt3": "3. Uploaded Attachment (Teams)",
            "auto_category_hint": "Category will be auto-classified",
            "reporter": "Reporter",
            "submit": "Submit",
            "auto": "(auto classified)"
        },
        "ja": {
            "title": "IT 問い合わせの提出",
            "summary": "件名",
            "desc": "説明（必須：症状・手順・期待）",
            "category": "分類",
            "priority": "優先度",
            "paste_hint": "このチャットに画像／ファイルを貼り付け／ドラッグすると、自動でチケットに添付します。",
            "upload_options": "ファイルのアップロード方法",
            "opt1": "1. インライン添付（画像を貼り付け）",
            "opt2": "2. インターネット添付（URL）",
            "opt3": "3. アップロード済み添付（Teams）",
            "auto_category_hint": "分類はシステムが自動判定します",
            "reporter": "申請者",
            "submit": "送信",
            "auto": "（自動分類）"
        }
    }

    t = texts.get(language, texts["zh"])
    category_choices = [{"title": c.get("label", c.get("code")), "value": c.get("code")} for c in categories]
    priority_choices = [
        {"title": "P1 - 緊急", "value": "P1"},
        {"title": "P2 - 高", "value": "P2"},
        {"title": "P3 - 中", "value": "P3"},
        {"title": "P4 - 低", "value": "P4"}
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
                "placeholder": "請描述問題現象、重現步驟、預期結果與影響",
                "height": "stretch"
            },
            {"type": "TextBlock", "text": t.get("auto_category_hint", t.get("auto", "")), "wrap": True, "spacing": "Small", "size": "Small", "color": "Good"},
            {"type": "Input.ChoiceSet", "id": "priority", "label": t["priority"], "choices": priority_choices, "value": "P3"},
            {"type": "TextBlock", "text": t["paste_hint"], "wrap": True, "spacing": "Small", "size": "Small"},
            {"type": "TextBlock", "text": f"{t['reporter']}: {reporter_name} <{reporter_email}>", "wrap": True, "spacing": "Small", "size": "Small", "color": "Accent"}
        ],
        "actions": [
            {"type": "Action.Submit", "title": f"✅ {t['submit']}", "data": {"action": "submitIT"}}
        ]
    }

    return Activity(type=ActivityTypes.message, attachments=[_adaptive_attachment(card_content)])
