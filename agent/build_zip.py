"""AgentCore Runtime に上げる zip を作る（Linux arm64 / Python 3.13 用）。

AgentCore Runtime は arm64 だけで動くため、依存ライブラリは手元のPC用ではなく
Linux arm64（manylinux2014 aarch64）用を集める必要がある。このスクリプトがそれを行う。
集め方は公式ドキュメントと同じ uv を使う。

準備（初回だけ）:
    python -m pip install uv

使い方（agent フォルダで）:
    python build_zip.py

できるもの:
    dist/deployment_package.zip   （zip の一番上に main.py がある）

オプション:
    --python-version 3.13     Runtime で選ぶ Python のバージョン（既定 3.13）
    --skip-config-check       config.json の必須項目が空でも作る（テスト用）
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIST_DIR = HERE / "dist"
OUTPUT = DIST_DIR / "deployment_package.zip"

APP_FILES = ("main.py", "config.json")
REQUIRED_CONFIG = ("MODEL_ID", "KB_ID", "DOCS_BUCKET")
EXCLUDE_TOP_DIRS = {"bin", "Scripts"}  # 実行用スクリプトのフォルダ（Runtime では使わない）
MAX_ZIP_BYTES = 250 * 1024 * 1024
MAX_UNZIPPED_BYTES = 750 * 1024 * 1024
FILE_MODE = 0o100644
DIR_MODE = 0o040755


def check_config() -> None:
    data = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
    missing = [key for key in REQUIRED_CONFIG if not str(data.get(key, "")).strip()]
    if missing:
        sys.exit(
            "config.json の次の項目が空です: "
            + ", ".join(missing)
            + "\n手順書の「6-1」を見て値を書いてから、もう一度実行してください。"
        )
    kb_type = str(data.get("KB_TYPE", "managed")).strip().lower()
    if kb_type not in ("managed", "custom"):
        sys.exit("config.json の KB_TYPE は managed か custom にしてください。")


def find_uv() -> list:
    """uv の呼び出し方を返す。uv コマンド → python -m uv の順に探す。"""
    exe = shutil.which("uv")
    if exe:
        return [exe]
    try:
        subprocess.run([sys.executable, "-m", "uv", "--version"], check=True, capture_output=True)
        return [sys.executable, "-m", "uv"]
    except (subprocess.CalledProcessError, OSError):
        return []


def install_dependencies(package_dir: Path, python_version: str) -> None:
    # 公式ドキュメントと同じく uv を使う。pip は「Windows だけで必要な部品」などを手元の Windows を
    # 基準に判断してしまい、Linux 用の部品を正しく集められないため使わない。
    uv = find_uv()
    if not uv:
        sys.exit(
            "uv が見つかりません。次のコマンドで入れてから、もう一度実行してください。\n"
            "    python -m pip install uv"
        )
    command = uv + [
        "pip", "install",
        "--python-platform", "aarch64-manylinux2014",
        "--python-version", python_version,
        "--target", str(package_dir),
        "--only-binary=:all:",
        "-r", str(HERE / "requirements.txt"),
    ]
    print("[1/3] 依存ライブラリ（Linux arm64 用）を集めています…")
    print("      " + " ".join(command))
    subprocess.run(command, check=True)


def copy_app_files(package_dir: Path) -> None:
    print("[2/3] main.py と config.json を入れています…")
    for name in APP_FILES:
        shutil.copy2(HERE / name, package_dir / name)


def _zip_info(path: Path, arcname: str, is_dir: bool) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo.from_file(path, arcname)
    info.create_system = 3  # Unix。Windows で作っても下の権限が使われるようにする
    if is_dir:
        info.external_attr = (DIR_MODE << 16) | 0x10
    else:
        info.external_attr = FILE_MODE << 16
        info.compress_type = zipfile.ZIP_DEFLATED
    return info


def make_zip(package_dir: Path) -> tuple:
    print("[3/3] zip を作っています…")
    DIST_DIR.mkdir(exist_ok=True)
    if OUTPUT.exists():
        OUTPUT.unlink()
    file_count = 0
    unzipped_bytes = 0
    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(package_dir):
            root_path = Path(root)
            rel_root = root_path.relative_to(package_dir)
            at_top = rel_root == Path(".")
            dirs[:] = sorted(
                d for d in dirs if d != "__pycache__" and not (at_top and d in EXCLUDE_TOP_DIRS)
            )
            if not at_top:
                zf.writestr(_zip_info(root_path, rel_root.as_posix() + "/", is_dir=True), b"")
            for name in sorted(files):
                if name.endswith((".pyc", ".pyo")):
                    continue
                path = root_path / name
                arcname = (rel_root / name).as_posix()
                data = path.read_bytes()
                zf.writestr(_zip_info(path, arcname, is_dir=False), data)
                file_count += 1
                unzipped_bytes += len(data)
    return OUTPUT.stat().st_size, unzipped_bytes, file_count


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentCore Runtime 用の zip を作る")
    parser.add_argument("--python-version", default="3.13")
    parser.add_argument("--skip-config-check", action="store_true")
    args = parser.parse_args()

    if not args.skip_config_check:
        check_config()

    # 作業フォルダはプロジェクトの外（一時フォルダ）に作る。
    # Windows で作業フォルダを消すときに「使用中」で失敗するのを避けるため。
    work_dir = Path(tempfile.mkdtemp(prefix="kq-agent-build-"))
    package_dir = work_dir / "package"
    package_dir.mkdir()
    try:
        install_dependencies(package_dir, args.python_version)
        copy_app_files(package_dir)
        zip_bytes, unzipped_bytes, file_count = make_zip(package_dir)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    print()
    print(f"できました: {OUTPUT}")
    print(f"  ファイル数: {file_count}")
    print(f"  zip の大きさ: {zip_bytes / 1024 / 1024:.1f} MB（上限 250 MB）")
    print(f"  展開後の大きさ: {unzipped_bytes / 1024 / 1024:.1f} MB（上限 750 MB）")
    if zip_bytes > MAX_ZIP_BYTES or unzipped_bytes > MAX_UNZIPPED_BYTES:
        sys.exit("大きさの上限を超えています。requirements.txt を見直してください。")
    print("次は手順書の「6-2」に進み、この zip を AgentCore のコンソールでアップロードします。")


if __name__ == "__main__":
    main()
