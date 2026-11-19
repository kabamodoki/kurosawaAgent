"""冒険者ギルドAPI（仮）— AgentCore のエージェントから呼ばれる Lambda。

実際の外部APIには接続しない。「呼ぶはずだった」リクエスト（メソッド・URL・本文）を
would_call に入れて返し、同じ内容を CloudWatch Logs に出す。

入力: {"action": "...", "params": {...}}
出力: {"ok": true, "mock": true, "action": ..., "would_call": {...}, "data": {...}, "note": ...}
      {"ok": false, "mock": true, "action": ..., "error": "..."}
"""

import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

JST = timezone(timedelta(hours=9))
BASE_URL = os.environ.get("GUILD_API_BASE_URL", "https://api.kurosawa-guild.example/v1")
NOTE = "これは仮のサービスの応答です。実際の外部APIには接続していません。"
SHOP_NAME = "黒澤村の道具屋（仮データ）"

# 道具の在庫（仮データ）。値段はマニュアル 06 と同じ。
ITEMS = {
    "やくそう": {"price_gold": 8, "stock": 12},
    "上やくそう": {"price_gold": 30, "stock": 4},
    "どくけし": {"price_gold": 10, "stock": 7},
    "澄み水": {"price_gold": 25, "stock": 5},
    "たいまつ": {"price_gold": 5, "stock": 20},
    "帰り羽": {"price_gold": 40, "stock": 3},
    "気つけ団子": {"price_gold": 60, "stock": 2},
}

# 言い換え（漢字で書かれたときなど）
ALIASES = {
    "薬草": "やくそう",
    "上薬草": "上やくそう",
    "毒消し": "どくけし",
    "松明": "たいまつ",
    "帰り羽根": "帰り羽",
}

RANKS = ("銅", "銀", "金", "黒鉄")
QUEST_STATUSES = ("冒険者募集中", "冒険者が向かっています", "達成報告待ち")
QUEST_ID_PATTERN = re.compile(r"^KQ-\d{8}-[0-9A-F]{4}$")


class BadRequest(Exception):
    """params の誤り。呼び出し元にそのまま伝える。"""


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", str(text)).strip()


def _require_text(params: dict, name: str) -> str:
    value = params.get(name)
    if value is None or _normalize(value) == "":
        raise BadRequest(f"{name} がありません")
    return _normalize(value)


def _log_would_call(would_call: dict) -> None:
    print(json.dumps({"mock_external_call": would_call}, ensure_ascii=False))


def check_item_stock(params: dict) -> tuple[dict, dict]:
    item_name = _require_text(params, "item_name")
    canonical = ALIASES.get(item_name, item_name)
    would_call = {"method": "GET", "url": f"{BASE_URL}/items/{quote(canonical)}/stock"}
    item = ITEMS.get(canonical)
    if item is None:
        data = {
            "item_name": item_name,
            "found": False,
            "message": "この道具は道具屋で扱っていません（仮データ）",
        }
    else:
        data = {
            "item_name": canonical,
            "found": True,
            "price_gold": item["price_gold"],
            "stock": item["stock"],
            "shop": SHOP_NAME,
        }
    return would_call, data


def register_quest(params: dict) -> tuple[dict, dict]:
    title = _require_text(params, "title")
    rank = _require_text(params, "rank")
    location = _require_text(params, "location")
    requester = _require_text(params, "requester")
    if rank not in RANKS:
        raise BadRequest(f"rank は {' / '.join(RANKS)} のどれかにしてください（受け取った値: {rank}）")

    raw_reward = params.get("reward_gold")
    if isinstance(raw_reward, bool):
        raise BadRequest("reward_gold は0以上の整数にしてください")
    try:
        reward_gold = int(_normalize(raw_reward).replace(",", "").replace("ゴールド", ""))
    except (TypeError, ValueError):
        raise BadRequest("reward_gold は0以上の整数にしてください") from None
    if reward_gold < 0:
        raise BadRequest("reward_gold は0以上の整数にしてください")

    now = datetime.now(JST)
    date_text = now.strftime("%Y%m%d")
    digest = hashlib.sha256(f"{title}|{requester}|{location}|{date_text}".encode("utf-8")).hexdigest()
    quest_id = f"KQ-{date_text}-{digest[:4].upper()}"

    body = {
        "title": title,
        "rank": rank,
        "reward_gold": reward_gold,
        "location": location,
        "requester": requester,
    }
    would_call = {"method": "POST", "url": f"{BASE_URL}/quests", "body": body}
    data = {
        "quest_id": quest_id,
        "status": "受付済み（冒険者募集中）",
        "registered_at": now.isoformat(timespec="seconds"),
    }
    return would_call, data


def get_quest_status(params: dict) -> tuple[dict, dict]:
    quest_id = _require_text(params, "quest_id").upper()
    if not QUEST_ID_PATTERN.match(quest_id):
        raise BadRequest("依頼番号の形式が違います（例: KQ-20261119-1A2B）")
    digest = hashlib.sha256(quest_id.encode("utf-8")).hexdigest()
    status = QUEST_STATUSES[int(digest[:2], 16) % len(QUEST_STATUSES)]
    would_call = {"method": "GET", "url": f"{BASE_URL}/quests/{quest_id}"}
    data = {"quest_id": quest_id, "status": status}
    return would_call, data


ACTIONS = {
    "check_item_stock": check_item_stock,
    "register_quest": register_quest,
    "get_quest_status": get_quest_status,
}


def lambda_handler(event, context):
    if not isinstance(event, dict):
        return {"ok": False, "mock": True, "action": None, "error": "入力は JSON のオブジェクトにしてください"}

    action = event.get("action")
    params = event.get("params") or {}
    handler = ACTIONS.get(action)
    if handler is None:
        return {
            "ok": False,
            "mock": True,
            "action": action,
            "error": f"action は {' / '.join(ACTIONS)} のどれかにしてください",
        }
    if not isinstance(params, dict):
        return {"ok": False, "mock": True, "action": action, "error": "params は JSON のオブジェクトにしてください"}

    try:
        would_call, data = handler(params)
    except BadRequest as exc:
        return {"ok": False, "mock": True, "action": action, "error": str(exc)}

    _log_would_call(would_call)
    return {
        "ok": True,
        "mock": True,
        "action": action,
        "would_call": would_call,
        "data": data,
        "note": NOTE,
    }
