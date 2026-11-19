"""テストの共通部品。各フォルダのモジュールを、名前がぶつからないように読み込む。"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def root() -> Path:
    return ROOT


@pytest.fixture()
def guild_lambda():
    return load_module("kq_guild_lambda", ROOT / "lambda" / "lambda_function.py")


@pytest.fixture()
def ec2_app():
    return load_module("kq_ec2_app", ROOT / "ec2_app" / "app.py")


@pytest.fixture()
def agent_main():
    return load_module("kq_agent_main", ROOT / "agent" / "main.py")


@pytest.fixture()
def chat_app():
    return load_module("kq_chat_app", ROOT / "local_chat" / "chat_app.py")
