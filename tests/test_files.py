"""配る・貼り付けるファイルの形のテスト。手順書どおりに作業して壊れないことを確かめる。"""

import json
import re

import pytest

PASTED_ON_EC2 = [
    "ec2_app/app.py",
    "ec2_app/master_rules.md",
    "ec2_app/requirements.txt",
    "ec2_app/kq-chat.service",
]

REFUSAL = "申し訳ありません。このチャットでは『黒澤クエスト』と『冒険者ギルドAPI（仮）』に関するご質問にだけお答えしています。"


@pytest.mark.parametrize("relative", PASTED_ON_EC2)
def test_files_pasted_with_heredoc_are_safe(root, relative):
    text = (root / relative).read_text(encoding="utf-8")
    assert "\t" not in text, "タブがあると、貼り付けのときにシェルの補完が働いて中身が崩れる"
    assert "\r" not in text
    assert all(line.strip() != "EOF" for line in text.splitlines()), "EOF だけの行があると、貼り付けが途中で終わる"


@pytest.mark.parametrize("name", ["start_tunnel.bat", "start_chat.bat"])
def test_batch_files_are_ascii_and_crlf(root, name):
    raw = (root / "local_chat" / name).read_bytes()
    raw.decode("ascii")  # 日本語があると、コマンドプロンプトで文字化けする
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b""), "改行は CRLF にそろえる"


def test_tunnel_uses_port_forwarding_document(root):
    text = (root / "local_chat" / "start_tunnel.bat").read_text(encoding="ascii")
    assert "--document-name AWS-StartPortForwardingSession" in text
    assert "portNumber=8000,localPortNumber=%LOCAL_PORT%" in text


@pytest.mark.parametrize(
    "name, placeholders",
    [
        ("ec2-role-invoke-agent.json", {"ACCOUNT_ID": 2, "RUNTIME_ID": 2}),
        ("agent-runtime-tools.json", {"ACCOUNT_ID": 5, "KB_ID": 1}),
        ("local-user-port-forward.json", {"ACCOUNT_ID": 1, "INSTANCE_ID": 1}),
    ],
)
def test_iam_policies(root, name, placeholders):
    text = (root / "iam" / name).read_text(encoding="utf-8")
    policy = json.loads(text)
    assert policy["Version"] == "2012-10-17"
    for word, count in placeholders.items():
        # 手順書に書いた「置き換える場所の数」と合っていること
        assert len(re.findall(rf"(?<![A-Z_]){word}(?![A-Z_])", text)) == count, word


def test_ec2_policy_allows_runtime_and_endpoint(root):
    policy = json.loads((root / "iam" / "ec2-role-invoke-agent.json").read_text(encoding="utf-8"))
    statement = policy["Statement"][0]
    assert statement["Action"] == "bedrock-agentcore:InvokeAgentRuntime"
    assert statement["Resource"][0].endswith(":runtime/RUNTIME_ID")
    assert statement["Resource"][1].endswith(":runtime/RUNTIME_ID/*")


def test_manual_has_ten_items(root):
    files = sorted((root / "data" / "manual").glob("*.md"))
    assert len(files) == 10
    for number, path in enumerate(files, 1):
        assert path.name.startswith(f"{number:02d}-")
        assert path.read_text(encoding="utf-8").startswith(f"# 黒澤クエスト マニュアル {number:02d}:")


def test_refusal_sentence_is_the_same_everywhere(root, agent_main):
    master_rules = (root / "ec2_app" / "master_rules.md").read_text(encoding="utf-8")
    assert REFUSAL in master_rules
    assert REFUSAL in agent_main.DEFAULT_MASTER_RULES


def test_streamlit_config(root):
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10 には tomllib がない（pytest と一緒に入る tomli を使う）
        import tomli as tomllib

    config = tomllib.loads((root / "local_chat" / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert config["server"]["address"] == "127.0.0.1"  # LAN に公開しない
    assert config["server"]["showEmailPrompt"] is False
    assert config["browser"]["gatherUsageStats"] is False


def test_shipped_config_is_valid_json(root):
    data = json.loads((root / "agent" / "config.json").read_text(encoding="utf-8"))
    assert data["KB_TYPE"] in ("managed", "custom")
    assert data["GUILD_LAMBDA_NAME"] == "kq-guild-api-mock"
