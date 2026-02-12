import os
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from features.it_support.intent_classifier import ITIntentClassifier

def test_classifier():
    classifier = ITIntentClassifier()
    
    sample_text = (
        "Hi xx, \n\n"
        "請參考附件預計報到人員資訊申請書, 並請協助帳號設定, 謝謝!\n\n"
        "以上, 如有任何問題請與我聯繫。"
    )
    
    code, label = classifier.classify(sample_text)
    print(f"Text: {sample_text[:50]}...")
    print(f"Result: code={code}, label={label}")
    
    expected_code = "onboarding"
    if code == expected_code:
        print("✅ Classification SUCCESS")
    else:
        print(f"❌ Classification FAILED (Expected {expected_code})")

if __name__ == "__main__":
    test_classifier()
