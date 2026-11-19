"""冒険者ギルドAPI（仮）の Lambda のテスト（basic-design 5.4・9）。"""

import re


def test_check_item_stock_found(guild_lambda):
    res = guild_lambda.lambda_handler({"action": "check_item_stock", "params": {"item_name": "やくそう"}}, None)
    assert res["ok"] is True and res["mock"] is True
    assert res["data"] == {
        "item_name": "やくそう",
        "found": True,
        "price_gold": 8,
        "stock": 12,
        "shop": "黒澤村の道具屋（仮データ）",
    }
    assert res["would_call"]["method"] == "GET"
    assert res["would_call"]["url"].startswith("https://api.kurosawa-guild.example/v1/items/")
    assert "実際の外部APIには接続していません" in res["note"]


def test_check_item_stock_alias_and_normalize(guild_lambda):
    res = guild_lambda.lambda_handler({"action": "check_item_stock", "params": {"item_name": " 薬草 "}}, None)
    assert res["data"]["item_name"] == "やくそう"
    assert res["data"]["found"] is True


def test_prices_match_manual(guild_lambda, root):
    manual = (root / "data" / "manual" / "06-items.md").read_text(encoding="utf-8")
    for name, item in guild_lambda.ITEMS.items():
        row = next(line for line in manual.splitlines() if line.startswith(f"| {name} |"))
        assert f"{item['price_gold']}ゴールド" in row, name


def test_check_item_stock_not_found(guild_lambda):
    res = guild_lambda.lambda_handler({"action": "check_item_stock", "params": {"item_name": "ドラゴンの卵"}}, None)
    assert res["ok"] is True
    assert res["data"]["found"] is False


def test_check_item_stock_missing_param(guild_lambda):
    res = guild_lambda.lambda_handler({"action": "check_item_stock", "params": {}}, None)
    assert res["ok"] is False
    assert "item_name" in res["error"]


def _quest_params(**overrides):
    params = {
        "title": "北の沼地の大ナマズ退治",
        "rank": "銀",
        "reward_gold": 1200,
        "location": "北の沼地",
        "requester": "黒澤村の村長 ミナモ",
    }
    params.update(overrides)
    return params


def test_register_quest(guild_lambda):
    res = guild_lambda.lambda_handler({"action": "register_quest", "params": _quest_params()}, None)
    assert res["ok"] is True
    assert re.match(r"^KQ-\d{8}-[0-9A-F]{4}$", res["data"]["quest_id"])
    assert res["data"]["status"] == "受付済み（冒険者募集中）"
    assert res["would_call"]["method"] == "POST"
    assert res["would_call"]["body"]["reward_gold"] == 1200


def test_register_quest_same_input_same_id(guild_lambda):
    a = guild_lambda.lambda_handler({"action": "register_quest", "params": _quest_params()}, None)
    b = guild_lambda.lambda_handler({"action": "register_quest", "params": _quest_params()}, None)
    assert a["data"]["quest_id"] == b["data"]["quest_id"]


def test_register_quest_reward_text(guild_lambda):
    res = guild_lambda.lambda_handler({"action": "register_quest", "params": _quest_params(reward_gold="1,200ゴールド")}, None)
    assert res["ok"] is True
    assert res["would_call"]["body"]["reward_gold"] == 1200


def test_register_quest_bad_rank(guild_lambda):
    res = guild_lambda.lambda_handler({"action": "register_quest", "params": _quest_params(rank="ダイヤ")}, None)
    assert res["ok"] is False
    assert "rank" in res["error"]


def test_register_quest_bad_reward(guild_lambda):
    for bad in (-1, "たくさん", None, True):
        res = guild_lambda.lambda_handler({"action": "register_quest", "params": _quest_params(reward_gold=bad)}, None)
        assert res["ok"] is False, bad


def test_get_quest_status(guild_lambda):
    res = guild_lambda.lambda_handler({"action": "get_quest_status", "params": {"quest_id": "kq-20261119-1a2b"}}, None)
    assert res["ok"] is True
    assert res["data"]["quest_id"] == "KQ-20261119-1A2B"
    assert res["data"]["status"] in guild_lambda.QUEST_STATUSES
    again = guild_lambda.lambda_handler({"action": "get_quest_status", "params": {"quest_id": "KQ-20261119-1A2B"}}, None)
    assert again["data"]["status"] == res["data"]["status"]


def test_get_quest_status_bad_id(guild_lambda):
    res = guild_lambda.lambda_handler({"action": "get_quest_status", "params": {"quest_id": "12345"}}, None)
    assert res["ok"] is False


def test_unknown_action_and_bad_input(guild_lambda):
    assert guild_lambda.lambda_handler({"action": "delete_everything"}, None)["ok"] is False
    assert guild_lambda.lambda_handler({"action": "check_item_stock", "params": "x"}, None)["ok"] is False
    assert guild_lambda.lambda_handler("not a dict", None)["ok"] is False
