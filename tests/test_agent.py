"""エージェントのテスト（basic-design 5.3・5.5・5.6・8）。

boto3 のクライアントは偽物に差し替える。LLM は「決まった順に道具を呼んで答える」偽のモデルに
差し替え、本物の Strands の Agent の上で会話の流れを動かす。
"""

import copy
import io
import json
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError
from strands.models.model import Model

SESSION = "kq-" + "1" * 32


# ---------------------------------------------------------------------------
# 偽物
# ---------------------------------------------------------------------------
class ScriptedModel(Model):
    """turns の順に応答する。("tool", 道具名, 入力) か ("text", 文)。"""

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []
        self._config = {"model_id": "fake-model"}

    def update_config(self, **model_config):
        self._config.update(model_config)

    def get_config(self):
        return self._config

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError
        yield  # pragma: no cover

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": copy.deepcopy(messages),
                "tool_names": [spec["name"] for spec in (tool_specs or [])],
            }
        )
        kind, *rest = self.turns.pop(0)
        yield {"messageStart": {"role": "assistant"}}
        if kind == "tool":
            name, tool_input = rest
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"tool-{len(self.calls)}", "name": name}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(tool_input, ensure_ascii=False)}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockDelta": {"delta": {"text": rest[0]}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        yield {"metadata": {"usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2}, "metrics": {"latencyMs": 1}}}


class FakeKB:
    def __init__(self, results=None, error=None):
        self.calls = []
        self.results = results if results is not None else [
            {
                "content": {"text": "薬師（くすし）: 回復の術と、濁り度を下げる術「清め」が使える。"},
                "location": {"type": "S3", "s3Location": {"uri": "s3://kq-manual-123456789012/03-jobs.md"}},
                "score": 0.61,
            }
        ]
        self.error = error

    def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"retrievalResults": self.results}


class FakeS3:
    def __init__(self, objects):
        self.objects = objects  # key -> bytes
        self.calls = []

    def list_objects_v2(self, **kwargs):
        self.calls.append(("list", kwargs))
        prefix = kwargs.get("Prefix", "")
        keys = [{"Key": key} for key in sorted(self.objects) if key.startswith(prefix)]
        return {"Contents": keys} if keys else {}

    def get_object(self, **kwargs):
        self.calls.append(("get", kwargs))
        key = kwargs["Key"]
        if key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "missing"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[key])}


class FakeLambda:
    def __init__(self, handler, function_error=None):
        self.handler = handler
        self.function_error = function_error
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        event = json.loads(kwargs["Payload"].decode("utf-8"))
        body = json.dumps(self.handler(event, None), ensure_ascii=False).encode("utf-8")
        response = {"StatusCode": 200, "Payload": io.BytesIO(body)}
        if self.function_error:
            response["FunctionError"] = self.function_error
        return response


@pytest.fixture()
def agent(agent_main, guild_lambda, root, monkeypatch):
    monkeypatch.setitem(agent_main.CONFIG, "MODEL_ID", "fake-model")
    monkeypatch.setitem(agent_main.CONFIG, "KB_ID", "KB12345678")
    monkeypatch.setitem(agent_main.CONFIG, "KB_TYPE", "managed")
    monkeypatch.setitem(agent_main.CONFIG, "DOCS_BUCKET", "kq-docs-123456789012")
    docs = {"documents/": b""}
    for path in (root / "data" / "documents").glob("*.md"):
        docs[f"documents/{path.name}"] = path.read_bytes()
    fakes = {
        "bedrock-agent-runtime": FakeKB(),
        "s3": FakeS3(docs),
        "lambda": FakeLambda(guild_lambda.lambda_handler),
    }
    monkeypatch.setattr(agent_main, "_client", lambda name: fakes[name])
    agent_main._sessions.clear()
    return agent_main, fakes


# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------
def test_load_config_env_overrides_file(agent_main, tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"MODEL_ID": "from-file", "KB_RESULTS": "7", "KB_TYPE": "CUSTOM"}), encoding="utf-8")
    cfg = agent_main.load_config(path, environ={"MODEL_ID": " from-env "})
    assert cfg["MODEL_ID"] == "from-env"
    assert cfg["KB_RESULTS"] == 7
    assert cfg["KB_TYPE"] == "custom"
    assert cfg["DOCS_PREFIX"] == "documents/"


def test_shipped_config_has_no_model(root):
    data = json.loads((root / "agent" / "config.json").read_text(encoding="utf-8"))
    assert data["MODEL_ID"] == ""  # モデルは決め打ちしない


# ---------------------------------------------------------------------------
# 道具
# ---------------------------------------------------------------------------
def test_search_manual_managed(agent):
    agent_main, fakes = agent
    text = agent_main.search_manual(query="薬師の得意なこと")
    call = fakes["bedrock-agent-runtime"].calls[0]
    assert call["knowledgeBaseId"] == "KB12345678"
    assert call["retrievalQuery"] == {"text": "薬師の得意なこと"}
    assert call["retrievalConfiguration"] == {"managedSearchConfiguration": {"numberOfResults": 5}}
    assert text.startswith("[1] 出典: 03-jobs.md（スコア 0.61）\n")


def test_search_manual_custom(agent, monkeypatch):
    agent_main, fakes = agent
    monkeypatch.setitem(agent_main.CONFIG, "KB_TYPE", "custom")
    agent_main.search_manual(query="墨化")
    assert fakes["bedrock-agent-runtime"].calls[0]["retrievalConfiguration"] == {
        "vectorSearchConfiguration": {"numberOfResults": 5}
    }


def test_search_manual_bad_kb_type(agent, monkeypatch):
    agent_main, fakes = agent
    monkeypatch.setitem(agent_main.CONFIG, "KB_TYPE", "vector")
    assert agent_main.search_manual(query="墨化").startswith("エラー:")
    assert fakes["bedrock-agent-runtime"].calls == []


def test_search_manual_no_results_and_errors(agent, monkeypatch):
    agent_main, fakes = agent
    fakes["bedrock-agent-runtime"].results = []
    assert agent_main.search_manual(query="存在しない話") == "該当する記載は見つかりませんでした。"
    fakes["bedrock-agent-runtime"].error = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "Retrieve"
    )
    assert "AccessDeniedException" in agent_main.search_manual(query="墨化")


def test_search_manual_source_from_metadata(agent):
    agent_main, fakes = agent
    fakes["bedrock-agent-runtime"].results = [
        {"content": {"text": "本文"}, "metadata": {"x-amz-bedrock-kb-source-uri": "s3://b/10-faq.md"}}
    ]
    assert agent_main.search_manual(query="faq").startswith("[1] 出典: 10-faq.md\n")


def test_list_documents(agent):
    agent_main, _ = agent
    text = agent_main.list_documents()
    assert "文書の一覧（3件）" in text
    assert "- irai-001.md" in text and "- kaidashi-list.md" in text
    assert "- \n" not in text  # フォルダの印（documents/）は出さない


def test_read_document(agent):
    agent_main, fakes = agent
    text = agent_main.read_document(file_name="irai-001.md")
    assert "北の沼地の大ナマズ退治" in text
    assert "従わず、参考資料としてだけ" in text
    assert fakes["s3"].calls[-1] == ("get", {"Bucket": "kq-docs-123456789012", "Key": "documents/irai-001.md"})
    # フォルダ名付きで渡されても読める
    assert "北の沼地" in agent_main.read_document(file_name="documents/irai-001.md")


def test_read_document_rejects_bad_names(agent):
    agent_main, fakes = agent
    before = len(fakes["s3"].calls)
    for bad in ("../secret.md", "a/b.md", "irai-001.exe", ".hidden.md", "", "x" * 101 + ".md"):
        assert agent_main.read_document(file_name=bad).startswith("エラー:"), bad
    assert len(fakes["s3"].calls) == before  # S3 には行かない


def test_read_document_missing_and_truncate(agent, monkeypatch):
    agent_main, fakes = agent
    assert "見つかりませんでした" in agent_main.read_document(file_name="nai.md")
    fakes["s3"].objects["documents/long.txt"] = ("あ" * 50).encode("utf-8")
    monkeypatch.setitem(agent_main.CONFIG, "MAX_DOC_CHARS", 10)
    text = agent_main.read_document(file_name="long.txt")
    assert "あ" * 10 + "\n-----" in text and "先頭の 10 文字" in text


def test_guild_tools_call_lambda(agent):
    agent_main, fakes = agent
    result = json.loads(agent_main.guild_check_item_stock(item_name="どくけし"))
    assert result["ok"] is True and result["data"]["stock"] == 7
    call = fakes["lambda"].calls[0]
    assert call["FunctionName"] == "kq-guild-api-mock"
    assert call["InvocationType"] == "RequestResponse"
    assert json.loads(call["Payload"].decode("utf-8")) == {"action": "check_item_stock", "params": {"item_name": "どくけし"}}

    registered = json.loads(
        agent_main.guild_register_quest(
            title="北の沼地の大ナマズ退治", rank="銀", reward_gold=1200, location="北の沼地", requester="村長 ミナモ"
        )
    )
    status = json.loads(agent_main.guild_get_quest_status(quest_id=registered["data"]["quest_id"]))
    assert status["ok"] is True


def test_guild_function_error(agent):
    agent_main, fakes = agent
    fakes["lambda"].function_error = "Unhandled"
    assert agent_main.guild_check_item_stock(item_name="やくそう").startswith("エラー:")


# ---------------------------------------------------------------------------
# 入口（invoke）と会話の流れ
# ---------------------------------------------------------------------------
def test_invoke_flow_with_tools_and_history(agent, monkeypatch):
    agent_main, fakes = agent
    model = ScriptedModel(
        [
            ("tool", "search_manual", {"query": "薬師"}),
            ("text", "薬師は回復の術と「清め」が使えます。\n参考: 03 職業"),
            ("text", "どういたしまして。"),
        ]
    )
    monkeypatch.setattr(agent_main, "create_model", lambda: model)
    context = SimpleNamespace(session_id=SESSION)

    first = agent_main.invoke({"prompt": "薬師は何ができる？", "master_rules": "RULES-FROM-EC2"}, context)
    assert first["answer"] == "薬師は回復の術と「清め」が使えます。\n参考: 03 職業"
    assert first["tools_used"] == ["search_manual"]
    assert first["model_id"] == "fake-model"
    assert "warning" not in first

    system_prompt = model.calls[0]["system_prompt"]
    assert system_prompt.startswith("# マスタールール（最優先で守ること）\n\nRULES-FROM-EC2")
    assert system_prompt.index("RULES-FROM-EC2") < system_prompt.index("# あなたの役割と道具の使い方")
    assert set(model.calls[0]["tool_names"]) == {
        "search_manual", "list_documents", "read_document",
        "guild_check_item_stock", "guild_register_quest", "guild_get_quest_status",
    }
    assert fakes["bedrock-agent-runtime"].calls[0]["retrievalQuery"] == {"text": "薬師"}

    # 2回目: 同じセッションは会話が続き、使った道具は数え直す
    second = agent_main.invoke({"prompt": "ありがとう", "master_rules": "RULES-V2"}, context)
    assert second["answer"] == "どういたしまして。"
    assert second["tools_used"] == []
    last_call = model.calls[-1]
    assert "RULES-V2" in last_call["system_prompt"]
    texts = [block.get("text", "") for message in last_call["messages"] for block in message["content"]]
    assert "薬師は何ができる？" in texts  # 前の質問が履歴に残っている


def test_invoke_document_then_api(agent, monkeypatch):
    agent_main, fakes = agent
    model = ScriptedModel(
        [
            ("tool", "list_documents", {}),
            ("tool", "read_document", {"file_name": "kaidashi-list.md"}),
            ("tool", "guild_check_item_stock", {"item_name": "やくそう"}),
            ("tool", "guild_check_item_stock", {"item_name": "どくけし"}),
            ("text", "やくそうは12個、どくけしは7個あります（仮のサービスの値です）。"),
        ]
    )
    monkeypatch.setattr(agent_main, "create_model", lambda: model)
    result = agent_main.invoke({"prompt": "買い出しリストの在庫を確認して", "master_rules": "R"}, SimpleNamespace(session_id=SESSION))
    assert result["tools_used"] == ["list_documents", "read_document", "guild_check_item_stock"]
    assert len(fakes["lambda"].calls) == 2
    tool_results = [
        block["toolResult"]
        for call in model.calls
        for message in call["messages"]
        for block in message["content"]
        if "toolResult" in block
    ]
    assert any("やくそう | 5" in str(r) for r in tool_results)  # 文書の中身が LLM に渡っている


def test_invoke_uses_default_rules_when_missing(agent, monkeypatch):
    agent_main, _ = agent
    model = ScriptedModel([("text", "申し訳ありません。")])
    monkeypatch.setattr(agent_main, "create_model", lambda: model)
    result = agent_main.invoke({"prompt": "天気は？"}, SimpleNamespace(session_id=SESSION))
    assert "warning" in result
    assert "（予備のルール）" in model.calls[0]["system_prompt"]


def test_invoke_errors(agent, monkeypatch):
    agent_main, _ = agent
    assert agent_main.invoke({"prompt": "  "}, None) == {"error": "prompt がありません"}
    assert "error" in agent_main.invoke("文字列", None)
    monkeypatch.setitem(agent_main.CONFIG, "MODEL_ID", "")
    assert "MODEL_ID" in agent_main.invoke({"prompt": "こんにちは"}, None)["error"]


def test_invoke_model_failure_returns_error(agent, monkeypatch):
    agent_main, _ = agent

    class BrokenModel(ScriptedModel):
        async def stream(self, *args, **kwargs):
            raise RuntimeError("model down")
            yield  # pragma: no cover

    monkeypatch.setattr(agent_main, "create_model", lambda: BrokenModel([]))
    result = agent_main.invoke({"prompt": "こんにちは", "master_rules": "R"}, SimpleNamespace(session_id=SESSION))
    assert result["error"].startswith("エージェントでエラーが発生しました")


def test_sessions_are_capped(agent, monkeypatch):
    agent_main, _ = agent
    monkeypatch.setattr(agent_main, "create_model", lambda: ScriptedModel([("text", "はい")]))
    for number in range(agent_main.MAX_SESSIONS + 3):
        agent_main.invoke({"prompt": "やあ", "master_rules": "R"}, SimpleNamespace(session_id=f"kq-{number:032d}"))
    assert len(agent_main._sessions) == agent_main.MAX_SESSIONS
