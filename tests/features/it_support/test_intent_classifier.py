import pytest
from features.it_support.intent_classifier import ITIntentClassifier


@pytest.fixture
def classifier():
    return ITIntentClassifier()


class TestITIntentClassifier:
    def test_empty_input_returns_other(self, classifier):
        code, label = classifier.classify("")
        assert code == "other"

    def test_none_input_returns_other(self, classifier):
        code, label = classifier.classify(None)
        assert code == "other"

    def test_printer_keywords(self, classifier):
        code, _ = classifier.classify("印表機卡紙無法列印")
        assert code == "printer"

    def test_network_keywords(self, classifier):
        code, _ = classifier.classify("網路斷線連不上")
        assert code == "network"

    def test_vpn_keywords(self, classifier):
        code, _ = classifier.classify("VPN 連不上 FortiClient")
        assert code == "vpn_remote"

    def test_account_keywords(self, classifier):
        code, _ = classifier.classify("帳號鎖定無法登入")
        assert code == "account_access"

    def test_hardware_keywords(self, classifier):
        code, _ = classifier.classify("筆電螢幕故障")
        assert code == "hardware"

    def test_software_keywords(self, classifier):
        code, _ = classifier.classify("Office 軟體安裝失敗")
        assert code == "software"

    def test_permission_keywords(self, classifier):
        code, _ = classifier.classify("申請資料夾權限")
        assert code == "permission"

    def test_email_teams_keywords(self, classifier):
        code, _ = classifier.classify("郵件收不到")
        assert code == "email_teams"

    def test_data_request_keywords(self, classifier):
        code, _ = classifier.classify("需要匯出報表")
        assert code == "data_request"

    def test_onboarding_keywords(self, classifier):
        code, _ = classifier.classify("新進人員報到開通帳號")
        assert code == "onboarding"

    def test_system_incident_keywords(self, classifier):
        code, _ = classifier.classify("系統異常服務中斷")
        assert code == "system_incident"

    def test_unrelated_text_returns_other(self, classifier):
        code, _ = classifier.classify("今天天氣不錯想去散步")
        assert code == "other"

    def test_label_is_nonempty_string(self, classifier):
        _, label = classifier.classify("印表機")
        assert isinstance(label, str)
        assert len(label) > 0

    def test_all_taxonomy_codes_have_labels(self, classifier):
        for cat in classifier.categories:
            code = cat["code"]
            label = classifier._label_for(code)
            assert label and isinstance(label, str)
