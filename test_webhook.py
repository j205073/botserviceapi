#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import requests
import json

# Bot address
BOT_URL = "https://rinnai-py-api-gfamdebjesaqapct.japanwest-01.azurewebsites.net/api/asana/webhook"

# Mock Asana webhook payload - task completed event
webhook_payload = {
    "events": [
        {
            "action": "changed",
            "resource": {
                "gid": "1208683560453534",
                "resource_type": "task",
                "name": "Test Task - Complete"
            },
            "parent": {
                "gid": "1208327275974093",
                "resource_type": "project"
            }
        }
    ]
}

print("Sending mock webhook event...")
print("URL: " + BOT_URL)
print("Payload: " + json.dumps(webhook_payload, indent=2))

response = requests.post(BOT_URL, json=webhook_payload)
print("\nResponse status: " + str(response.status_code))
print("Response content: " + response.text)

if response.status_code == 200:
    print("\nWebhook test successful! Check:")
    print("1. Azure logs for webhook event")
    print("2. Reporter email for Teams push/Email")
    print("3. SharePoint for knowledge base entry")
else:
    print("\nWebhook test failed, check logs")
