"""ローカルのチャット画面のテスト（basic-design 6）。EC2 は偽物に差し替える。"""

import requests
from streamlit.testing.v1 import AppTest


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


def _app(root):
    return AppTest.from_file(str(root / "local_chat" / "chat_app.py"), default_timeout=30)


def test_session_id_meets_agentcore_rule(chat_app):
    session_id = chat_app.new_session_id()
    assert len(session_id) >= 33 and session_id.startswith("kq-")


def test_chat_shows_answer_and_tools(root, monkeypatch):
    sent = []

    def fake_post(url, json=None, timeout=None):
        sent.append((url, json, timeout))
        return FakeResponse(200, {"answer": "薬師は回復が得意です。", "tools_used": ["search_manual"], "session_id": json["session_id"], "elapsed_ms": 5})

    monkeypatch.setattr(requests, "post", fake_post)
    at = _app(root)
    at.run()
    assert at.title[0].value == "黒澤クエスト 案内チャット"

    at.chat_input[0].set_value("薬師は何ができる？").run()
    assert not at.exception
    url, body, timeout = sent[0]
    assert url == "http://127.0.0.1:8000/chat"
    assert body["message"] == "薬師は何ができる？"
    assert len(body["session_id"]) >= 33
    assert timeout == 310
    markdowns = [m.value for m in at.markdown]
    assert "薬師は回復が得意です。" in markdowns
    assert any("使った道具: search_manual" in c.value for c in at.caption)

    # 同じ画面で2問目を送ると、同じセッションIDが使われる
    at.chat_input[0].set_value("ありがとう").run()
    assert sent[1][1]["session_id"] == body["session_id"]


def test_chat_shows_connection_error(root, monkeypatch):
    def fake_post(url, json=None, timeout=None):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(requests, "post", fake_post)
    at = _app(root)
    at.run()
    at.chat_input[0].set_value("こんにちは").run()
    assert any("ポート転送（start_tunnel.bat）" in e.value for e in at.error)


def test_chat_shows_server_detail(root, monkeypatch):
    monkeypatch.setattr(requests, "post", lambda url, json=None, timeout=None: FakeResponse(502, {"detail": "AgentCore の呼び出しに失敗しました: AccessDeniedException: x"}))
    at = _app(root)
    at.run()
    at.chat_input[0].set_value("こんにちは").run()
    assert any("502" in e.value and "AccessDeniedException" in e.value for e in at.error)


def test_new_conversation_resets(root, monkeypatch):
    monkeypatch.setattr(requests, "post", lambda url, json=None, timeout=None: FakeResponse(200, {"answer": "はい", "tools_used": []}))
    at = _app(root)
    at.run()
    at.chat_input[0].set_value("一つ目").run()
    old_session = at.session_state["session_id"]
    assert len(at.session_state["messages"]) == 2
    at.sidebar.button[1].click().run()  # 新しい会話をはじめる
    assert at.session_state["messages"] == []
    assert at.session_state["session_id"] != old_session


def test_health_check_button(root, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda url, timeout=None: FakeResponse(200, {"status": "ok", "version": "0.1.0", "agent_configured": True}))
    at = _app(root)
    at.run()
    at.sidebar.button[0].click().run()  # 接続を確認
    assert any("EC2 につながりました" in s.value for s in at.success)
