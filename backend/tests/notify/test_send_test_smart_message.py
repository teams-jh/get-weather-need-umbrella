import pytest

import notify.manual_message as workflow


def test_build_request_uses_fixed_template_and_user_key(monkeypatch):
    monkeypatch.setenv("TOSS_TEST_USER_KEY", "test-user")
    monkeypatch.delenv("TOSS_TEST_ANON_KEY", raising=False)
    monkeypatch.setenv("TOSS_TEST_DEPLOYMENT_ID", "019abfe8-fd68-7021-9cdc-30d6053cc009")
    monkeypatch.setenv(
        "TOSS_TEST_MESSAGE_CONTEXT",
        '{"notificationLocationName":"서울 강남","preparationNames":"우산, 양산"}',
    )
    monkeypatch.setenv("TOSS_MTLS_CERT_PATH", "/tmp/client.crt")
    monkeypatch.setenv("TOSS_MTLS_KEY_PATH", "/tmp/client.key")

    headers, body, certificate = workflow.build_request()

    assert headers["x-toss-user-key"] == "test-user"
    assert "x-anon-key" not in headers
    assert body["templateSetCode"] == "need-umbrella-NEED_UMBRELLA_MORNING_V2"
    assert body["context"] == {
        "notificationLocationName": "서울 강남",
        "preparationNames": "우산, 양산",
    }
    assert certificate == ("/tmp/client.crt", "/tmp/client.key")


def test_build_request_rejects_multiple_recipient_keys(monkeypatch):
    monkeypatch.setenv("TOSS_TEST_USER_KEY", "test-user")
    monkeypatch.setenv("TOSS_TEST_ANON_KEY", "test-anon")

    with pytest.raises(ValueError, match="exactly one"):
        workflow.recipient_header()


def test_message_context_uses_dynamic_template_defaults(monkeypatch):
    monkeypatch.delenv("TOSS_TEST_MESSAGE_CONTEXT", raising=False)

    assert workflow.message_context() == {
        "notificationLocationName": "서울 강남",
        "preparationNames": "우산, 양산",
    }
