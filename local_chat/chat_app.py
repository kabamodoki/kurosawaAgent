"""黒澤クエスト 案内チャット（ローカルPC用・Streamlit）。

ポート転送（start_tunnel.bat）で、EC2 の受付API が http://127.0.0.1:8000 に
見えている前提で動く。

起動: start_chat.bat
      （または: streamlit run chat_app.py --server.address 127.0.0.1 --server.port 8501）
"""

import os
import uuid

import requests
import streamlit as st

API_URL = os.environ.get("KQ_API_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = int(os.environ.get("KQ_TIMEOUT", "310"))

EXAMPLES = [
    "黒澤クエストはどんなゲーム？",
    "薬師は何ができる？",
    "墨化したらどうすればいい？",
    "文書の一覧を見せて",
    "依頼書 irai-001.md を読んで、ギルドに登録して",
    "買い出しリストの道具の在庫を確認して",
    "今日の東京の天気は？（断られることを確かめる）",
]


class ChatError(Exception):
    """画面に出すエラー。"""


def new_session_id() -> str:
    """AgentCore のセッションIDの条件（33文字以上）を満たすIDを作る。"""
    return "kq-" + uuid.uuid4().hex


def ask(session_id: str, message: str) -> dict:
    """EC2 の /chat に質問を送り、{"answer", "tools_used", ...} を返す。"""
    try:
        response = requests.post(
            f"{API_URL}/chat",
            json={"session_id": session_id, "message": message},
            timeout=TIMEOUT,
        )
    except requests.exceptions.ConnectionError:
        raise ChatError("EC2 に接続できません。ポート転送（start_tunnel.bat）が動いているか確認してください。") from None
    except requests.exceptions.Timeout:
        raise ChatError("時間内に答えが返りませんでした。少し待ってから、もう一度送ってください。") from None

    if response.status_code != 200:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = response.text
        if isinstance(detail, list):  # FastAPI の入力チェックのエラー
            detail = " / ".join(str(item.get("msg", item)) if isinstance(item, dict) else str(item) for item in detail)
        raise ChatError(f"エラー（{response.status_code}）: {detail}")
    return response.json()


def check_health() -> tuple[bool, str]:
    try:
        response = requests.get(f"{API_URL}/health", timeout=10)
    except requests.exceptions.RequestException:
        return False, "EC2 に接続できません。ポート転送（start_tunnel.bat）が動いているか確認してください。"
    if response.status_code != 200:
        return False, f"EC2 から {response.status_code} が返りました。"
    data = response.json()
    if not data.get("agent_configured"):
        return False, "EC2 にはつながりましたが、AGENT_RUNTIME_ARN が設定されていません。"
    return True, f"EC2 につながりました（受付API {data.get('version', '?')}）。"


def init_state() -> None:
    if "session_id" not in st.session_state:
        st.session_state.session_id = new_session_id()
    if "messages" not in st.session_state:
        st.session_state.messages = []


def render_message(message: dict) -> None:
    with st.chat_message(message["role"]):
        if message.get("error"):
            st.error(message["content"])
        else:
            st.markdown(message["content"])
        if message.get("tools"):
            st.caption("使った道具: " + "、".join(message["tools"]))


def main() -> None:
    st.set_page_config(page_title="黒澤クエスト 案内チャット")
    init_state()

    st.title("黒澤クエスト 案内チャット")
    st.caption("ローカルPC → SSM → EC2 → AgentCore の検証用チャットです。")

    with st.sidebar:
        st.subheader("接続先")
        st.code(API_URL)
        if st.button("接続を確認"):
            ok, text = check_health()
            if ok:
                st.success(text)
            else:
                st.error(text)
        if st.button("新しい会話をはじめる"):
            st.session_state.session_id = new_session_id()
            st.session_state.messages = []
        st.caption(f"セッションID: {st.session_state.session_id}")
        st.subheader("質問の例")
        st.markdown("\n".join(f"- {example}" for example in EXAMPLES))

    for message in st.session_state.messages:
        render_message(message)

    prompt = st.chat_input("黒澤クエストについて質問してください")
    if prompt:
        user_message = {"role": "user", "content": prompt}
        st.session_state.messages.append(user_message)
        render_message(user_message)

        with st.spinner("考え中です…"):
            try:
                data = ask(st.session_state.session_id, prompt)
                reply = {
                    "role": "assistant",
                    "content": data.get("answer") or "（答えが空でした）",
                    "tools": data.get("tools_used", []),
                }
            except ChatError as exc:
                reply = {"role": "assistant", "content": str(exc), "error": True}
        st.session_state.messages.append(reply)
        render_message(reply)


if __name__ == "__main__":
    main()
