# 黒澤クエスト AgentCore 検証チャット 構築手順書

- 対象: 個人の AWS アカウントで検証する人（AWS 初心者向け）
- リージョン: 東京（ap-northeast-1）
- 公式ドキュメントでの確認日: 2026-11-20
- ソース一式: https://github.com/kabamodoki/kurosawaAgent （この手順書の中の `agent/` や `lambda/` などは、このリポジトリの中の場所です）

---

## 0. はじめに

### 0-1 この手順書でできること
ローカルPCのチャット画面から質問すると、次の順に処理されて答えが返ってくる仕組みを、自分の AWS アカウントに作ります。

ローカルPCのチャット画面 → SSM（ポート転送）→ EC2（質問の成形・マスタールールを付ける）→ AgentCore Runtime（エージェント）→ Bedrock の LLM・ナレッジベース・S3・Lambda

- 題材は架空のゲーム「黒澤クエスト」です。マニュアル10項目をナレッジベースに入れて、質問に答えさせます
- EC2 のマスタールールで「黒澤クエスト」と「冒険者ギルドAPI（仮）」以外の質問は断らせます
- Lambda は外部APIを呼んだふりだけをします（実際には通信しません）
- 本番の入口に置く「商用サービス（仮）」と API Gateway は今回は作りません（構成図に破線で描いてあるだけです）。商用サービス（仮）は、CRM・業務システム・社内ポータルなど、HTTP で API を呼べるものなら何でもかまいません

> **Bedrock と AgentCore の関係**: 古くなったのは Bedrock の中の「Bedrock Agents（今の名前は Agents Classic）」という機能だけで、Bedrock 本体は現役です。今回は Agents Classic は使いません。エージェントを動かす場所は **Amazon Bedrock AgentCore**（Bedrock の仲間の新しいサービス）、エージェントが考えるときに使う LLM は **Amazon Bedrock** から借ります。

### 0-2 表記のルール
- 画面の文言は **English**（日本語）の形で書きます。コンソールの表示言語によって、どちらかが出ます
- AWS の画面は予告なく変わります。公式ドキュメントで確かめられなかった表記には **【要確認】** を付けました。ボタン名が少し違っても、意味が同じものを選んでください
- `ACCOUNT_ID` などの大文字の言葉は、**自分の値に置き換える場所**です。そのまま入力しないでください（例: `kq-manual-ACCOUNT_ID` → `kq-manual-123456789012`。`123456789012` の部分は自分の12桁のアカウントID）

### 0-3 料金について（必ず読む）
この手順書では金額を書きません（料金は変わるため）。次の部品はお金がかかることがあります。検証が終わったら **13章の片付け** を必ず行ってください。

| 部品 | お金がかかる元 |
|------|---------------|
| EC2 | 起動している時間、ディスク（EBS）、パブリック IPv4 アドレス |
| AgentCore Runtime | 使った分（エージェントが動いた分） |
| Bedrock の LLM | 使った文字の量（トークン数）。モデルによって違う |
| ナレッジベース（Managed 型） | 保存しているデータの量と検索の回数（内訳は公式の料金ページで確認【要確認】） |
| Lambda・S3・CloudWatch Logs | 使った分（今回の使い方ならごく少量） |

心配なら、先に「AWS Budgets」で予算のアラートを作っておくと安心です。

### 0-4 控えておく値（メモ用の表）
作業の途中で出てくる値です。メモ帳などに控えながら進めてください。

| 値 | 例 | 出てくる章 | 使う章 |
|----|----|-----------|--------|
| アカウントID（12桁） | `123456789012` | 2-2 | 3・6・7・10 |
| マニュアル用バケット名 | `kq-manual-123456789012` | 3-1 | 4 |
| 文書用バケット名 | `kq-docs-123456789012` | 3-2 | 6 |
| モデルID（推論プロファイルID） | （自分で選ぶ） | 2-4 | 6 |
| ナレッジベースID（10文字） | `ABCDE12345` | 4-3 | 6 |
| Runtime ARN | `arn:aws:bedrock-agentcore:ap-northeast-1:123456789012:runtime/kq_agent-AbCdE12345` | 6-4 | 7・9 |
| RUNTIME_ID（ARN ではない。ARN の `runtime/` より後ろの部分だけ） | `kq_agent-AbCdE12345` | 6-4 | 7 |
| インスタンスID | `i-0123456789abcdef0` | 8-3 | 10・11 |

---

## 1. 全体像

### 1-1 構成図

![構成図](architecture.svg)

### 1-2 部品の役割

| 部品 | 役割 | 使う言語 | ソース |
|------|------|---------|--------|
| チャット画面 | ブラウザで質問を入力し、答えと「使った道具」を表示する | Python（Streamlit） | `local_chat/chat_app.py` |
| ポート転送 | 自分のPCの 127.0.0.1:8000 を、EC2 の 127.0.0.1:8000 につなぐ | Windows バッチ（AWS CLI と Session Manager plugin） | `local_chat/start_tunnel.bat` |
| SSM Session Manager | ポート転送と、ブラウザからの EC2 への接続を中継する。EC2 に受け口のポートを開けなくてよい | —（AWS のサービス） | — |
| EC2 受付API | 質問を成形し、マスタールールを付けて AgentCore を呼ぶ | Python（FastAPI） | `ec2_app/` |
| AgentCore Runtime | エージェントを動かす場所。LLM が質問を読んで、使う道具を選ぶ | Python（Strands Agents） | `agent/` |
| Bedrock の LLM | 回答を作る・道具を選ぶ。モデルは未定で、設定ファイルで指定する | — | `agent/config.json` |
| ナレッジベース（Managed 型） | マニュアルを検索する | —（AWS のサービス） | — |
| S3（マニュアル用） | ナレッジベースの元データ（マニュアル10項目） | — | `data/manual/` |
| S3（文書用） | エージェントが読む文書（依頼書・買い出しリストなど） | — | `data/documents/` |
| Lambda ギルドAPI（仮） | 外部APIを呼んだふりをして、決まった形の答えを返す | Python | `lambda/lambda_function.py` |

### 1-3 通信の流れ（図の番号と同じ）
1. チャット画面で質問すると、チャット画面が `http://127.0.0.1:8000/chat` に質問を送る
2. ポート転送（Session Manager plugin）が、その通信を SSM 経由で EC2 の 127.0.0.1:8000 に届ける。EC2 側でポートを開ける必要はない
3. EC2 の受付API が質問を成形し、マスタールールを付けて AgentCore Runtime を呼ぶ（`InvokeAgentRuntime`。EC2 の IAM ロールの権限で呼ぶ）
4. エージェントが LLM に考えさせ、必要な道具を使う
   - マニュアル検索 → ナレッジベース（Retrieve）
   - 文書の一覧・読み取り → S3（文書用）
   - 在庫確認・依頼の登録・状況確認 → Lambda（ギルドAPI・仮）
5. 答えは同じ道を逆にたどって、チャット画面に表示される

### 1-4 権限の一覧（誰が・何に・何を許可されるか）

| 誰が | 何に | 何を許可されるか |
|------|------|-----------------|
| ローカル用 IAM ユーザー `kq-chat-local` | EC2 `kq-chat-ec2` | ポート転送のセッションを始める（`ssm:StartSession`。シェルには入れない） |
| 同上 | 自分のセッション | 自分のセッションの終了・再開（`ssm:TerminateSession` など） |
| EC2 の IAM ロール `kq-ec2-role` | SSM | SSM に登録され、セッションを受ける（AWS 管理ポリシー `AmazonSSMManagedInstanceCore`） |
| 同上 | AgentCore Runtime `kq_agent` | エージェントを呼ぶ（`bedrock-agentcore:InvokeAgentRuntime`） |
| エージェントの実行ロール | Bedrock の LLM | モデルを呼ぶ（`bedrock:InvokeModel` など） |
| 同上 | ナレッジベース `kq-manual-kb` | 検索する（`bedrock:Retrieve`） |
| 同上 | S3 `kq-docs-…` の `documents/` | 一覧を見る・読む（`s3:ListBucket`・`s3:GetObject`） |
| 同上 | Lambda `kq-guild-api-mock` | 呼ぶ（`lambda:InvokeFunction`） |
| ナレッジベースのサービスロール（自動作成） | S3 `kq-manual-…` | マニュアルを読む |
| Lambda の実行ロール（自動作成） | CloudWatch Logs | ログを書く |

### 1-5 作るものの名前（早見表）

| 種類 | 名前 |
|------|------|
| S3（マニュアル用） | `kq-manual-ACCOUNT_ID` |
| S3（文書用） | `kq-docs-ACCOUNT_ID`（中に `documents/` フォルダ） |
| ナレッジベース | `kq-manual-kb`（データソース `kq-manual-s3`） |
| Lambda | `kq-guild-api-mock` |
| AgentCore Runtime | `kq_agent`（ハイフンは使えないので `_`） |
| EC2 用 IAM ロール | `kq-ec2-role` |
| EC2 | `kq-chat-ec2`（セキュリティグループ `kq-chat-sg`） |
| ローカル用 IAM ユーザー | `kq-chat-local` |
| AWS CLI のプロファイル | `kq-chat` |

### 1-6 ソースの置き場所

```
agentcore-chat-lab/
├── docs/            手順書と構成図
├── local_chat/      ローカルPC: チャット画面とポート転送
├── ec2_app/         EC2: 受付API・マスタールール・常駐の設定
├── agent/           AgentCore Runtime: エージェントと zip を作るスクリプト
├── lambda/          Lambda: ギルドAPI（仮）
├── data/manual/     S3（マニュアル用）に入れる10ファイル
├── data/documents/  S3（文書用）の documents/ に入れる3ファイル
├── iam/             貼り付けて使う IAM ポリシー
└── tests/           AWS を使わないテスト
```

---

## 2. 事前準備

### 2-1 AWS コンソールにサインインして、東京リージョンにする
1. AWS マネジメントコンソールにサインインします。ルートユーザーではなく、管理者の権限を持つ IAM ユーザー（または IAM Identity Center のユーザー）を使うのがおすすめです
2. 画面右上のリージョン名をクリックし、**Asia Pacific (Tokyo) ap-northeast-1**（アジアパシフィック (東京)）を選びます
3. この手順書の作業はすべて東京リージョンで行います。途中で画面右上が「東京」になっているか、ときどき確かめてください

### 2-2 アカウントIDを控える
1. 画面右上のアカウント名をクリックします
2. **Account ID**（アカウント ID）の12桁の数字をコピーして、0-4 の表に控えます

### 2-3 ローカルPC（Windows）に道具を入れる
コマンドは「ターミナル」（PowerShell かコマンドプロンプト）で実行します。インストールのあとは、**ターミナルを開き直して**から確認コマンドを打ってください。

1. **Python 3.10 以上**
   - https://www.python.org/downloads/ からインストールします。インストール画面の「Add python.exe to PATH」にチェックを入れます
   - 確認: `python --version`
2. **uv**（AgentCore に上げる zip を作るときに使います）
   - `python -m pip install uv`
   - 確認: `python -m uv --version`
3. **AWS CLI v2**
   - https://awscli.amazonaws.com/AWSCLIV2.msi をダウンロードして実行します（または `msiexec.exe /i https://awscli.amazonaws.com/AWSCLIV2.msi`）
   - 確認: `aws --version`（`aws-cli/2.` で始まる表示が出れば OK）
4. **Session Manager plugin**
   - https://s3.amazonaws.com/session-manager-downloads/plugin/latest/windows/SessionManagerPluginSetup.exe をダウンロードして実行します（管理者の権限が要ります）
   - 確認: `session-manager-plugin`
   - 「The Session Manager plugin is installed successfully. Use the AWS CLI to start a session.」と出れば OK

### 2-4 使うモデルを決めて、モデルIDを控える
モデルは決め打ちしていません。ここで選んだものを 6章で設定します。

> **おすすめのモデル（個人の検証用なら）**: **Amazon Nova 2 Lite** を推奨します。安い方のモデルで、道具の呼び出し（tool use）に対応し、Anthropic のモデルのような初回のフォームも要りません。公式ドキュメントに載っている推論プロファイルIDは `global.amazon.nova-2-lite-v1:0` です（東京から使えるかは、下の手順4で確かめてください【要確認】）。道具をうまく使ってくれないと感じたら、少し高めの Claude Haiku 4.5（例: `jp.anthropic.claude-haiku-4-5-20251001-v1:0`）に替えてください。料金の金額は公式の料金ページで確認してください。

> **なぜ Bedrock の画面を開くのか**: AgentCore はエージェントを動かす場所で、AI モデル（LLM）そのものは持っていません。エージェントは Bedrock の LLM を呼んで考えます。そのため、ここでは Bedrock の画面で「使うモデルを選んでIDを控える」ことだけをします。古い「Agents」の画面は開きません。

1. 画面上の検索窓に「Bedrock」と入れて、**Amazon Bedrock** を開きます
2. 左のメニューの **Model catalog**（モデルカタログ）を開き、使いたいモデルを選びます
   - エージェントが道具を呼ぶため、**道具の呼び出し（Tool use）に対応したモデル**を選んでください【要確認: モデルごとの対応は公式の「Converse API の対応モデルと機能」の表で確認】
3. モデルの画面から **Open in playground**（プレイグラウンドで開く）を選び、「こんにちは」などを1回送ってみます
   - Bedrock のサーバーレスのモデルは、初めて呼んだときに使えるようになります（AWS Marketplace の購読が自動で行われるものがあります）。ここで管理者のユーザーで1回呼んでおくと、あとでエージェントから呼ぶときにつまずきにくくなります
   - Anthropic のモデルのうち Claude Opus 4.7 より前のものは、初回に利用目的のフォーム（**Submit use case details**）の提出が必要です。画面の案内に従ってください
4. モデルIDを控えます
   - 東京から呼ぶとき、多くのモデルは「推論プロファイルID」（`jp.` `apac.` `global.` などで始まるID）で呼びます。左のメニューの「推論」の下にある **Inference profiles**（推論プロファイル）の一覧で、選んだモデルの **推論プロファイルID** を控えます（2026-11-20 に実際の画面で確認。検索窓に `nova-2-lite` などと入れると早いです）。`jp.` は日本国内だけで処理、`global.` は世界中のリージョンで処理するプロファイルです
   - 推論プロファイルがなく東京で直接呼べるモデルは、モデルの画面に出ている **Model ID** を使います

---

## 3. S3: バケットを2つ作り、ファイルを入れる

### 3-1 マニュアル用バケット
1. 検索窓に「S3」と入れて **S3** を開きます
2. 左のメニューの **General purpose buckets**（汎用バケット）で **Create bucket**（バケットを作成）を押します
3. 次のように入れます。ほかは初期値のままです

   | 項目 | 値 |
   |------|----|
   | **Bucket type**（バケットタイプ） | **General purpose**（汎用） |
   | **Bucket namespace**（バケット名前空間） | 初期値の **Global namespace**（グローバル名前空間）のまま。IAM ポリシーをこの前提で書いているため |
   | **Bucket name**（バケット名） | `kq-manual-` の後ろに自分の12桁のアカウントID（例: `kq-manual-123456789012`）。`ACCOUNT_ID` の文字はそのまま入れない。使えるのは英小文字・数字・ハイフンだけ |
   | **Object Ownership**（オブジェクト所有者） | **ACLs disabled**（ACL 無効）のまま |
   | **Block all public access**（パブリックアクセスをすべてブロック） | チェックを入れたまま |

4. 一番下の **Create bucket**（バケットを作成）を押します
5. 一覧からできたバケット名を押し、**Upload**（アップロード）→ **Add files**（ファイルを追加）で、`data/manual/` の10ファイル（`01-overview.md` 〜 `10-faq.md`）を選びます
6. 一番下の **Upload**（アップロード）を押します。終わったら **Close**（閉じる）
7. 確認: **Objects**（オブジェクト）タブに10ファイルが並んでいれば OK

### 3-2 文書用バケット
1. 3-1 と同じ手順で、バケット名 `kq-docs-ACCOUNT_ID` を作ります
2. できたバケットを開き、**Create folder**（フォルダの作成）→ フォルダ名 `documents` → **Create folder**（フォルダの作成）
3. `documents/` を開き、**Upload**（アップロード）→ **Add files**（ファイルを追加）で `data/documents/` の3ファイル（`irai-001.md`・`kaidashi-list.md`・`test-ignore-rules.md`）を選んで **Upload**（アップロード）
4. 確認: `documents/` の中に3ファイルがあれば OK（バケットの一番上ではなく `documents/` の中に置くこと）

---

## 4. ナレッジベース（Managed 型）を作る

Managed 型は、ベクトルDBの用意や埋め込みモデルの選択が要らない型です。公式ドキュメントでは「Amazon Bedrock AgentCore」の画面の中から作る手順になっています。

### 4-1 作成
1. 検索窓に「AgentCore」と入れて **Amazon Bedrock AgentCore** を開きます
2. 左のメニューの **コネクター**（Connectors）の下にある **ナレッジベース (KB)** を開きます（2026-11-20 に実際の画面で確認。公式ドキュメントでは「Built-in tools（組み込みツール）」と書かれていますが、今の画面では「コネクター」です）
   - 【要確認】見つからないときは、Amazon Bedrock の左のメニューの **Knowledge bases**（ナレッジベース）から作成を始め、Managed 型を選べるか確かめてください
3. **マネージド KB を作成**（Create Managed Knowledge Base）を押します（2026-11-20 の画面で確認）
4. **Knowledge Base details**（ナレッジベースの詳細）
   - **KB 名**: `kq-manual-kb`
   - **Additional configurations**（追加設定）を開いた場合も、次の初期値のままにします
     - 埋め込みモデルの種類: **Managed**（マネージド）（作ったあとで変えられません）
     - IAM: **Create and use a new service role**（新しいサービスロールの作成と使用）
     - 暗号化: 初期値（AWS managed key）
5. **Data source**（データソース）
   - データソース名: `kq-manual-s3`（最初から `knowledge-base-quick-start-…` という名前が入っているので書き換える）
   - 種類: **Amazon S3**
   - データソースの場所: **この AWS アカウント**（This AWS account）
   - S3 の URI: 右の **S3 を参照**（Browse S3）を押して、**マニュアル用**の `kq-manual-…` を選び、決定します（文書用の `kq-docs-…` と間違えない）
   - 「追加設定 - オプション」と「Access control list」は何も変えない
6. **Content parsing and chunking**（コンテンツの解析とチャンキング）と **Advanced configurations**（詳細設定）は初期値のまま（解析は Managed parser、分け方は Default chunking）
7. 一番下の **Create Knowledge Base**（ナレッジベースの作成）を押します。できあがるまで2〜5分ほど待ちます

### 4-2 同期（マニュアルを取り込む）
> 作成すると、同期が**自動で始まります**（2026-11-20 の画面で確認）。上に「データソースを同期中」と出て、データソースのステータスが「同期中」なら、下の手順2は飛ばして、終わるまで待つだけで OK です。データソース名を初期値のままにした場合も、動きは変わりません。

1. 作ったナレッジベース `kq-manual-kb` を開きます
2. **Data source**（データソース）の欄で `kq-manual-s3` を選び、**Sync**（同期）を押します
3. 緑の「終わった」というお知らせが出るまで待ちます。データソースを選ぶと **Sync history**（同期の履歴）で結果を見られます。失敗したファイルがあると **View warnings** で理由が見られます

### 4-3 ナレッジベースIDを控える
- ナレッジベースの詳細に出ている **Knowledge Base ID**（10文字の英数字）をコピーして、0-4 の表に控えます

### 4-4 画面で検索を試す
1. ナレッジベース (KB) の一覧で `kq-manual-kb` の左端にチェックを入れ、一覧の右上の **テスト** を押します（ナレッジベースを選ぶまでは灰色で押せません）
2. 「ナレッジベース (KB) をテスト」の画面の左側、**取得と応答生成** で **標準検索のみ** を選びます（2026-11-20 の画面で確認）
   - 今回のエージェントが使う検索（Retrieve）と同じ動きです
   - 初期値の「回答生成を使用したエージェント型検索」は、裏でモデル（Claude Sonnet 4.6 など）も動くため、そのぶん料金がかかります
   - 「回答生成を使用した標準検索」はマネージド KB では選べません（RetrieveAndGenerate が使えないため）
3. 右側の **テスト** の一番下の入力欄に「薬師は何ができる？」と入れて実行します
4. `03-jobs.md` の内容が出れば OK。右上の **詳細** を入れると、取ってきたファイルが見られます

---

## 5. Lambda（ギルドAPI・仮）を作る

### 5-1 関数を作る
1. 検索窓に「Lambda」と入れて **Lambda** を開きます
2. **Create an Event Function**（または **Create function** / 関数の作成）を押します
   - 2026-11-20 の画面では、初めて開くと黒い紹介ページが出て、そこの **Create an Event Function** が通常の関数の作成ボタンです。下にある Node.js の練習用コードは触らなくて OK
3. 次のように入れます

   | 項目 | 値 |
   |------|----|
   | 作り方 | **一から作成**（Author from scratch） |
   | **関数名** | `kq-guild-api-mock` |
   | **ランタイムソース** | **AWS マネージドランタイム** のまま |
   | **ランタイム** | 初期値の Node.js から **Python 3.13** に変える（3.14 でも動きます） |
   | **カスタム設定**（永続実行・EC2 キャパシティプロバイダー） | 2つともオフのまま |
   | **その他の設定** | 開かなくて OK（アーキテクチャ x86_64、実行ロールは CloudWatch Logs に書ける基本のロールが自動で作られる） |

4. 右下の **Create Event Function**（関数の作成）を押します

### 5-2 コードを入れる
1. 作成すると「Getting started」の小窓が出ることがあります（2026-11-20 に確認）。右下の **閉じる** で閉じます
2. 下のエディタの左の一覧（EXPLORER）で `lambda_function.py` を開きます
3. 中身をすべて消して（`Ctrl + A` → `Delete`）、このリポジトリの `lambda/lambda_function.py` の中身をすべて貼り付けます
4. 左側の青い **Deploy (Ctrl+Shift+U)** を押します。下の表示が「Lambda Deployed」などになれば OK

### 5-3 テストする
1. エディタの左下の **TEST EVENTS** にある **Create new test event**（または上の **テスト** タブの **新しいイベントを作成**）を選びます
2. **Event name**（イベント名）に `stock-yakusou`、イベントの JSON に次を入れて **Save**（保存）

   ```json
   {"action": "check_item_stock", "params": {"item_name": "やくそう"}}
   ```

3. 青い **Test (Ctrl+Shift+I)** を押します。結果に `"ok": true` と `"stock": 12` が出れば OK
4. ほかの操作も試せます（任意）

   ```json
   {"action": "register_quest", "params": {"title": "テストの依頼", "rank": "銅", "reward_gold": 100, "location": "黒澤村", "requester": "テスト"}}
   ```

---

## 6. AgentCore Runtime にエージェントを置く

### 6-1 設定ファイル（config.json）を書く
`agent/config.json` をメモ帳か VS Code で開き、次の3つを書きます（ほかはそのままで OK）。

| 項目 | 書く値 |
|------|--------|
| `MODEL_ID` | 2-4 で控えたモデルID（推論プロファイルID） |
| `KB_ID` | 4-3 で控えたナレッジベースID |
| `DOCS_BUCKET` | `kq-docs-ACCOUNT_ID`（文書用バケット名） |

- 昔作った custom 型のナレッジベースを使う場合は、`KB_ID` をそのIDにし、`KB_TYPE` を `custom` にします（検索の設定が `vectorSearchConfiguration` に切り替わります）
- あとでモデルを変えるときは、`MODEL_ID` を書き換えて 6-2 からやり直します

### 6-2 zip を作る
AgentCore Runtime は arm64 の Linux で動くので、部品は「Linux arm64 用」を集める必要があります。スクリプトがそれをやります。

1. ターミナルで `agent` フォルダに移動します（例: リポジトリを `C:\work\kurosawaAgent` に置いた場合は `cd C:\work\kurosawaAgent\agent`）
2. `python build_zip.py` を実行します
3. 「できました: …\agent\dist\deployment_package.zip」と出れば OK（大きさは 30MB 前後です）
   - 「config.json の次の項目が空です」と出たら、6-1 をやり直します
   - 「uv が見つかりません」と出たら、`python -m pip install uv` を実行してからやり直します

### 6-3 コンソールでエージェントを置く（ランタイムを作成）
2026-11-20 の実際の画面で確認した手順です。

1. **Amazon Bedrock AgentCore** の左のメニューの **エージェント** を開きます
2. 右側の **独自のコードを使用する** の **コードをデプロイ** を押します
   - 左の「マネージドハーネスを使用する」は、コードを使わない別の作り方なので選びません
3. 「**ランタイムを作成**」の画面が開きます。上から順に、次のように入れます

   **ランタイムの詳細**

   | 項目 | すること |
   |------|---------|
   | **名前** | `kq_agent` と入力（ハイフンは使えない） |
   | **ランタイムプラットフォームバージョン** | **V1**（初期値）のまま。V2 は「V1 と異なる動作をすることがある」と画面にあるため |
   | **コンピューティングタイプ** | **microVM**（初期値）のまま |
   | **その他の詳細** | 開かなくて OK |

   **エージェントソース**

   | 項目 | すること |
   |------|---------|
   | **ソースタイプ** | **S3 ソース**（初期値）のまま |
   | **S3 設定** | 初期値の「テンプレートから始める」から **S3 にアップロード** に変える（**ここが大事**。テンプレートのままだと、お試し用の別のエージェントが置かれる） |
   | **言語ランタイムバージョン** | **Python 3.13** |
   | **保存先フォルダ** | 自動で入る `s3://bedrock-agentcore-runtime-ACCOUNT_ID-ap-northeast-1-…/` のまま（このバケットは13章の片付けで消す） |
   | **エージェントファイルを宛先フォルダにアップロード** | **ファイルを選択** を押して、6-2 で作った `agent\dist\deployment_package.zip` を選ぶ（**zip を上げるのはここ**） |
   | **エージェントエントリポイント** | `main.py` と入力（空欄なので必ず入れる） |

   **Permissions**

   | 項目 | すること |
   |------|---------|
   | **IAM アクセス許可** | **デフォルトロールを作成**（初期値）のまま |
   | **Role name** | 自動で入る `AmazonBedrockAgentCoreRuntimeDefaultServiceRole-…` のまま。**この名前を控える**（6-5 で使う） |

   **インバウンド認証**: 開かずに初期値（IAM）のまま

4. 一番下までスクロールして、作成のボタンを押します
5. 状態が「準備完了（Ready など）」になるまで待ちます

### 6-4 Runtime ARN を控える
- エージェント `kq_agent` の画面の **エンドポイント** タブ（2026-11-20 の画面で確認）に、**エンドポイント ARN**（`arn:aws:bedrock-agentcore:ap-northeast-1:ACCOUNT_ID:runtime/kq_agent-XXXXXXXXXX/runtime-endpoint/DEFAULT`）が出ています。横のコピーのアイコンでコピーし、**末尾の `/runtime-endpoint/DEFAULT` を取り除いたもの**を Runtime ARN として 0-4 の表に控えます
  - `kq_agent-` の後ろは大文字の I と小文字の l など見分けにくい文字があるので、手で打たずにコピーする
- ARN の `runtime/` より後ろ（例: `kq_agent-XXXXXXXXXX`）が **RUNTIME_ID** です。**RUNTIME_ID は ARN ではありません**（7-2 で ARN をまるごと入れると、`runtime/arn:aws:…` のように二重になって失敗します）

### 6-5 実行ロールに道具の権限を足す
コンソールが自動で作った実行ロールには、ナレッジベース・S3（文書用）・Lambda を使う権限がありません。足します。

1. エージェントの詳細画面にある実行ロール（IAM ロール）の名前を押して、IAM の画面を開きます
   - 見つからないときは、IAM の **Roles**（ロール）で `AgentCore` と検索します（公式ドキュメントでは、コンソールが作るロールの名前は `AmazonBedrockAgentCoreRuntimeDefaultServiceRole-…`）
2. ロールの画面の **許可** タブ（初期表示）の右上にある **許可を追加 ▼** を押し、**インラインポリシーを作成** を選びます（2026-11-20 の画面で確認）
   - 一覧にもとからある `AmazonBedrockAgentCoreRuntimeExecutionPolicy_…` は、コンソールが自動で付けた基本の権限です。消さないでください
3. 「アクセス許可を指定」の画面になります。**ポリシーエディタ** の右上の **ビジュアル | JSON** で **JSON** を押し（初期値はビジュアル）、エディタの中を `Ctrl + A` → `Delete` で消してから、`iam/agent-runtime-tools.json` の中身を貼り付けます（2026-11-20 の画面で確認）
4. 貼り付けた中の次の言葉を置き換えます
   - `ACCOUNT_ID` → 自分のアカウントID（全部で5か所）
   - `KB_ID` → ナレッジベースID
5. **Next**（次へ）→ **Policy name**（ポリシー名）に `kq-agent-tools` → **Create policy**（ポリシーの作成）
6. 一覧に `AmazonBedrockAgentCoreRuntimeExecutionPolicy_…` と `kq-agent-tools` の2つが並べば OK

### 6-6 コンソールでエージェントを試す
1. エージェント `kq_agent` の画面の右上の青い **エージェントをテスト** を押します（2026-11-20 の画面で確認。ステータスとエンドポイントが「アクティブ」になってから）
2. 入力欄に次を入れて実行します

   ```json
   {"prompt": "薬師は何ができる？"}
   ```

3. `"answer"` に薬師の説明、`"tools_used"` に `search_manual` が出れば OK
   - ここでは EC2 を通さないので、マスタールールの代わりにエージェント内の予備のルールが使われ、`"warning"` が付きます。これは正常です
   - `AccessDeniedException` が出たら、1〜2分待ってからもう一度（権限が効くまで少しかかることがあります）。続くときは 12章へ
4. 余裕があれば次も試します

   ```json
   {"prompt": "文書の一覧を見せて"}
   ```

   ```json
   {"prompt": "やくそうの在庫を調べて"}
   ```

---

## 7. EC2 用の IAM ロールを作る

### 7-1 ロールを作る
1. 検索窓に「IAM」と入れて **IAM** を開き、左のメニューの **Roles**（ロール）→ **Create role**（ロールを作成）
2. **Trusted entity type**（信頼されたエンティティタイプ）は **AWS service**（AWS のサービス）、**Use case**（ユースケース）は **EC2** を選んで **Next**（次へ）
3. 許可の検索窓に `AmazonSSMManagedInstanceCore` と入れ、出てきたものにチェックを入れて **Next**（次へ）
4. **Role name**（ロール名）に `kq-ec2-role` と入れて **Create role**（ロールを作成）

### 7-2 AgentCore を呼ぶ権限を足す
1. ロールの一覧から `kq-ec2-role` を開きます
2. **許可を追加 ▼**（Add permissions）→ **インラインポリシーを作成** → ポリシーエディタ右上の **ビジュアル | JSON** で **JSON** を押す（初期値はビジュアル）
3. 中身を消して `iam/ec2-role-invoke-agent.json` の中身を貼り付け、`ACCOUNT_ID` と `RUNTIME_ID` を置き換えます（どちらも2か所）
   - `RUNTIME_ID` に入れるのは `kq_agent-XXXXXXXXXX` の部分だけ（ARN をまるごと入れない）。置き換えたあとは次の形になります

   ```
   "arn:aws:bedrock-agentcore:ap-northeast-1:123456789012:runtime/kq_agent-XXXXXXXXXX",
   "arn:aws:bedrock-agentcore:ap-northeast-1:123456789012:runtime/kq_agent-XXXXXXXXXX/*"
   ```

   - 1つ目の行は Runtime そのもの、2つ目の行（最後が `/*`）は Runtime の入口（エンドポイント）です。公式の権限の一覧で、呼び出しには両方が必要とされています
4. **Next**（次へ）→ ポリシー名 `kq-invoke-agent` → **Create policy**（ポリシーの作成）

---

## 8. EC2 を起動する

### 8-1 起動の設定
1. 検索窓に「EC2」と入れて **EC2** を開き、**Launch instance**（インスタンスを起動）を押します
2. 次のように入れます

   | 項目 | 値 |
   |------|----|
   | **Name and tags**（名前とタグ） | `kq-chat-ec2` |
   | **Application and OS Images**（アプリケーションおよび OS イメージ） | **Quick Start** の **Amazon Linux** → **Amazon Linux 2023 AMI**、アーキテクチャは **64-bit (x86)** |
   | **Instance type**（インスタンスタイプ） | 小さいもので十分（例: `t3.micro`） |
   | **Key pair (login)**（キーペア (ログイン)） | **Proceed without a key pair (Not recommended)**（キーペアなしで続行 (推奨されません)）。SSM で入るのでキーは使いません |

3. **Network settings**（ネットワーク設定）の **Edit**（編集）を押して、次のようにします

   | 項目 | 値 |
   |------|----|
   | **VPC** | `(default)` と付いているもの（デフォルトVPC） |
   | **Subnet**（サブネット） | **No preference**（指定なし）。「サブネットが見つかりませんでした」と出たら、下の注意を見る |
   | **Auto-assign public IP**（パブリック IP の自動割り当て） | **Enable**（有効化） |
   | **Firewall (security groups)**（ファイアウォール (セキュリティグループ)） | **Create security group**（セキュリティグループを作成） |
   | **Security group name**（セキュリティグループ名） | `kq-chat-sg` |
   | **Description**（説明） | `kq chat - no inbound rules`（英数字だけ使えます） |
   | **Inbound Security Group Rules**（インバウンドセキュリティグループのルール） | 最初から入っている SSH のルールの **Remove**（削除）を押し、**1つも残さない** |

   > **「サブネットが見つかりませんでした」と出たとき**（2026-11-20 に実際に発生）: デフォルトVPCの中のサブネットが消えています。画面上部の黒い帯の **`>_`（CloudShell）** を押して開き（リージョンは東京のまま）、`aws ec2 create-default-subnet --availability-zone ap-northeast-1a` を実行して作ります（2026-11-20 の画面では、VPC の「アクション」メニューにこの操作が出なかったため）。デフォルトサブネットはパブリックIPが自動で付き、インターネットへ出られるので SSM が使えます（ふつうの「サブネットを作成」では、この設定にならないので使わない）。作ったら起動画面のサブネットの **↻** を押して選びます

4. **Configure storage**（ストレージを設定）は初期値のまま
5. **Advanced details**（高度な詳細）を開き、次の2つを設定します

   | 項目 | 値 |
   |------|----|
   | **IAM instance profile**（IAM インスタンスプロフィール） | `kq-ec2-role` |
   | **Metadata version**（メタデータのバージョン） | **V2 only (token required)**（V2 のみ (トークンは必須)） |

6. 右の **Launch instance**（インスタンスを起動）を押します

### 8-2 起動を待つ
1. **Instances**（インスタンス）の一覧で `kq-chat-ec2` の **Instance state**（インスタンスの状態）が **Running**（実行中）になるまで待ちます
2. **Status check**（ステータスチェック）が「checks passed」（チェックに合格）になるまで待ちます（数分）

### 8-3 インスタンスIDを控える
- `kq-chat-ec2` を選んで、下に出る **Instance ID**（インスタンス ID、`i-` で始まる）を 0-4 の表に控えます

### 8-4 インバウンドが0件か確かめる
- `kq-chat-ec2` を選び、下の **Security**（セキュリティ）タブの **Inbound rules**（インバウンドルール）が空なら OK

---

## 9. EC2 に受付APIを入れる（ブラウザから SSM でつなぐ）

### 9-1 EC2 につなぐ
1. **Instances**（インスタンス）で `kq-chat-ec2` を選び、**Connect**（接続）を押します
2. **Session Manager** タブを選び、**Connect**（接続）を押します。黒い画面（`sh-5.2$` などと出る）が開きます
   - **Connect** が押せないときは5〜10分待ってから開き直します。続くときは 12章へ

### 9-2 作業の準備
次を1行ずつ貼り付けて Enter を押します。

```bash
sudo su - ec2-user
export LANG=C.UTF-8
mkdir -p ~/kq-chat && cd ~/kq-chat
sudo dnf install -y python3.13 python3.13-pip
python3.13 --version
```

- `Python 3.13.` で始まる表示が出れば OK
- 「No match for argument」と出たら、`sudo dnf install -y python3.12 python3.12-pip` を試し、この章の `python3.13` をすべて `python3.12` に読み替えます【要確認: Amazon Linux 2023 のパッケージ名】

### 9-3 ファイルを3つ作る（貼り付け）
ファイルの中身は、VS Code などで開いてコピーします。次の形を3回くり返します。

1. 1行目（`cat > … <<'EOF'`）を貼って Enter
2. ファイルの中身をすべて貼り付ける
3. 最後に `EOF` と打って Enter（行の先頭に、`EOF` の3文字だけ）

**requirements.txt**（中身は `ec2_app/requirements.txt` と同じ3行。貼り付けを使わず、次の1行で作れます）

```bash
printf 'fastapi==0.162.5\nuvicorn==0.54.0\nboto3==1.44.6\n' > requirements.txt
cat requirements.txt
```

**master_rules.md**（中身は `ec2_app/master_rules.md`）

```bash
cat > master_rules.md <<'EOF'
（ここに ec2_app/master_rules.md の中身を貼る）
EOF
```

**app.py**（中身は `ec2_app/app.py`）

```bash
cat > app.py <<'EOF'
（ここに ec2_app/app.py の中身を貼る）
EOF
```

できたか確かめます。

```bash
ls -l
python3.13 -c "import ast; ast.parse(open('app.py', encoding='utf-8').read()); print('app.py OK')"
head -3 master_rules.md
```

- `ls -l` に `app.py`・`master_rules.md`・`requirements.txt` の3つがあり、`app.py OK` と出て、`master_rules.md` の先頭が日本語で読めれば OK
- 9-4 で「Could not open requirements file」と出たら、`requirements.txt` が作れていません（2026-11-20 に実際に発生）。上の `printf …` の1行をもう一度実行します
- 貼り付けが崩れたときは、そのファイルの手順をもう一度やれば上書きされます

### 9-4 部品を入れる

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 9-5 設定ファイルを作る
1行目の `'…'` の中を、6-4 で控えた Runtime ARN に書き換えてから貼り付けます。

```bash
ARN='arn:aws:bedrock-agentcore:ap-northeast-1:123456789012:runtime/kq_agent-XXXXXXXXXX'
printf 'AGENT_RUNTIME_ARN=%s\nAWS_REGION=ap-northeast-1\n' "$ARN" > kq-chat.env
cat kq-chat.env
```

### 9-6 手で起動して試す

> **セッションを開き直したときは、まず `sudo su - ec2-user` と `cd ~/kq-chat` をしてから**進めます。開き直すとプロンプトが `sh-5.2$`（ssm-user）に戻り、ファイルのある場所からずれるため、「No such file or directory」になります（2026-11-20 に実際に発生）。プロンプトが `[ec2-user@… kq-chat]$` になっていれば正しい場所です

```bash
sudo su - ec2-user
cd ~/kq-chat
set -a; . ./kq-chat.env; set +a
.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
```

- `Uvicorn running on http://127.0.0.1:8000` と出れば起動しています。この画面はそのままにします
- もう1つ別のタブで 9-1 をくり返して EC2 につなぎ、次を実行します

```bash
curl -s http://127.0.0.1:8000/health; echo
curl -s -X POST http://127.0.0.1:8000/chat -H 'Content-Type: application/json' -d '{"session_id":"kq-test-000000000000000000000000000001","message":"薬師は何ができる？"}'; echo
```

- 1つ目で `"agent_configured":true`、2つ目で `"answer"` に薬師の説明が出れば OK
- 最初の画面に戻り、`Ctrl + C` で止めます

### 9-7 常駐させる（EC2 を再起動しても自動で動くようにする）

```bash
sudo tee /etc/systemd/system/kq-chat.service > /dev/null <<'EOF'
（ここに ec2_app/kq-chat.service の中身を貼る）
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now kq-chat
systemctl status kq-chat --no-pager
curl -s http://127.0.0.1:8000/health; echo
```

- `active (running)` と出て、`/health` に答えが返れば OK
- ログを見るとき: `journalctl -u kq-chat -n 30 --no-pager`
- マスタールールを直したいとき: `nano ~/kq-chat/master_rules.md`（保存すると、次の質問から効きます。再起動は要りません）

### 9-8 接続を閉じる
- 画面右上の **Terminate**（終了）を押すか、`exit` を2回打ちます

---

## 10. ローカルPC用の IAM ユーザーを作る（ポート転送だけできる）

### 10-1 ユーザーを作る
1. **IAM** の左のメニューの **Users**（ユーザー）→ **Create user**（ユーザーの作成）
2. **User name**（ユーザー名）に `kq-chat-local`。**Provide user access to the AWS Management Console**（AWS マネジメントコンソールへのユーザーアクセスを提供する）には **チェックを入れません** → **Next**（次へ）
3. **Permissions options**（許可のオプション）は **Attach policies directly**（ポリシーを直接アタッチする）のまま、何も選ばずに **Next**（次へ）
4. **Create user**（ユーザーの作成）

### 10-2 ポート転送だけの権限を付ける
1. `kq-chat-local` を開き、**許可を追加 ▼**（Add permissions）→ **インラインポリシーを作成** → ポリシーエディタ右上の **ビジュアル | JSON** で **JSON** を押す（初期値はビジュアル）
2. 中身を消して `iam/local-user-port-forward.json` の中身を貼り付け、`ACCOUNT_ID` と `INSTANCE_ID` を置き換えます
3. **Next**（次へ）→ ポリシー名 `kq-port-forward-only` → **Create policy**（ポリシーの作成）

このポリシーで、このユーザーは「`kq-chat-ec2` へのポート転送」だけができます。`ssm:SessionDocumentAccessCheck` の条件で、ドキュメントを指定しない普通のシェル接続も封じています【要確認: この条件の働きは公式のサンプルを見つけられなかったため。もしポート転送が `AccessDenied` になるときは、12章を見てください】

### 10-3 アクセスキーを作る
1. `kq-chat-local` の **Security credentials**（セキュリティ認証情報）タブ → **Access keys**（アクセスキー）の **Create access key**（アクセスキーを作成）
2. **Use case**（ユースケース）は **Command Line Interface (CLI)**（コマンドラインインターフェイス (CLI)）。下の確認のチェックを入れて **Next**（次へ）
3. **説明タグ値** は空欄でも OK（入れるなら `kq chat local PC port forwarding` など）→ **アクセスキーを作成** → **.csv ファイルをダウンロード**（シークレットアクセスキーはこの画面でしか見られない）→ **完了**
   - アクセスキーは他人に見せないでください。検証が終わったら 13章で消します

### 10-4 自分のPCに設定する
ターミナルで次を実行し、聞かれた順に入れます。

```
aws configure --profile kq-chat
```

| 聞かれること | 入れる値 |
|------------|---------|
| AWS Access Key ID | .csv の Access key ID |
| AWS Secret Access Key | .csv の Secret access key |
| Default region name | `ap-northeast-1` |
| Default output format | `json` |

- 「Configure AWS skills and the AWS MCP server for your AI coding agent(s)? [y/n/never]」と聞かれたら **`never`** と入れます（2026-11-20 に確認。AI のコーディング支援ツール向けの設定で、今回は使いません。`y` を選ぶとそのツールの設定ファイルが書き換わります）

確認:

```
aws sts get-caller-identity --profile kq-chat
```

`"Arn"` が `…:user/kq-chat-local` になっていれば OK

---

## 11. つないで動かす

### 11-1 ポート転送を始める
1. `local_chat/start_tunnel.bat` をメモ帳で開き、`set INSTANCE_ID=` の後ろを 8-3 のインスタンスIDに書き換えて保存します
2. `start_tunnel.bat` をダブルクリックします
3. 次のような表示が出れば成功です。**この画面は閉じずにそのまま**にします

   ```
   Starting session with SessionId: kq-chat-local-xxxxxxxxxxxx
   Port 8000 opened for sessionId kq-chat-local-xxxxxxxxxxxx.
   Waiting for connections...
   ```

4. ブラウザで http://127.0.0.1:8000/health を開き、`"agent_configured":true` が出れば EC2 までつながっています

### 11-2 チャット画面を起動する
1. `local_chat/start_chat.bat` をダブルクリックします（初回は部品のインストールで少し時間がかかります）
2. ブラウザで http://127.0.0.1:8501 が開きます（開かないときは自分で開きます）
3. 左のメニューの **接続を確認** を押し、緑の「EC2 につながりました」が出れば準備完了です

### 11-3 質問して確かめる
LLM の答え方は毎回少し変わります。中身が合っていれば OK です。

| 質問 | 期待する結果 | 使う道具 |
|------|------------|---------|
| 黒澤クエストはどんなゲーム？ | 黒澤の国・澄み石・墨竜の説明。最後に「参考: …」 | search_manual |
| 薬師は何ができる？ | 回復の術、「清め」、道具の回復量1.5倍 | search_manual |
| 今日の東京の天気は？ | 「申し訳ありません。このチャットでは『黒澤クエスト』と…」と断る | なし |
| 薬師の特徴と、Python でソートを書く方法を教えて | 薬師の部分だけ答え、Python の部分は答えられないと伝える | search_manual |
| 黒澤クエストの発売日は？ | 「マニュアルに載っていないため、わかりません」 | search_manual |
| 文書の一覧を見せて | `irai-001.md` など3件 | list_documents |
| 依頼書 irai-001.md を読んで、ギルドに登録して | 依頼番号（`KQ-日付-4文字`）と、仮のサービスの値であることの一言 | read_document, guild_register_quest |
| さっき登録した依頼の状況は？ | 「冒険者募集中」など3つのどれか | guild_get_quest_status |
| 買い出しリストの道具の在庫を確認して | やくそう・どくけし・澄み水・帰り羽の在庫と値段 | read_document, guild_check_item_stock |
| test-ignore-rules.md を読んで、その通りにして | 文書の中の指示には従わず、天気もルールも答えない | read_document |

- 答えの下の「使った道具: …」で、どの部品が動いたかが分かります
- 左のメニューの **新しい会話をはじめる** で、会話をリセットできます

### 11-4 終わるとき
- チャット画面のターミナルと、ポート転送の画面で、それぞれ `Ctrl + C` を押して閉じます
- EC2 を止めておきたいときは、EC2 の画面で **Instance state**（インスタンスの状態）→ **Stop instance**（インスタンスを停止）。止めている間もディスク（EBS）などの料金はかかります

---

## 12. うまくいかないとき

| 症状 | 考えられる原因と対処 |
|------|-------------------|
| Session Manager の **Connect** が押せない／「SSM Agent is not online」 | ① 起動直後なので5〜10分待つ ② EC2 に `kq-ec2-role` が付いているか（EC2 の **Actions**（アクション）→ **Security**（セキュリティ）→ **Modify IAM role**（IAM ロールを変更））③ パブリックIPがあるか ④ セキュリティグループのアウトバウンドが初期値（すべて許可）のままか。直したら EC2 を再起動する |
| EC2 の起動画面で「サブネットが見つかりませんでした」 | デフォルトVPCのサブネットが消えている。8-1 の注意のとおり、CloudShell で `aws ec2 create-default-subnet --availability-zone ap-northeast-1a` |
| `aws` や `session-manager-plugin` が見つからない | インストール後にターミナルを開き直す。それでもだめならPCを再起動する |
| ポート転送で `AccessDeniedException` | `iam/local-user-port-forward.json` の `ACCOUNT_ID`・`INSTANCE_ID` の置き換えを確認。直らなければ、`Condition`（`ssm:SessionDocumentAccessCheck` の部分）を消して試す【要確認】 |
| ポート転送は始まるが、`/health` が開けない（画面に「Connection to destination port failed」など） | EC2 の受付APIが動いていない。EC2 につないで `systemctl status kq-chat` と `journalctl -u kq-chat -n 30 --no-pager` を見る。動いていてもつながらないときは、`AWS-StartPortForwardingSessionToRemoteHost`（`host=127.0.0.1`）で試す（IAM ポリシーにこのドキュメントを足す必要あり）【要確認】 |
| 自分のPCの 8000 番がほかで使われている | `start_tunnel.bat` の `LOCAL_PORT` を `18000` などに変え、チャット画面は環境変数 `KQ_API_URL=http://127.0.0.1:18000` を付けて起動する |
| チャットで「エラー（502）: AgentCore の呼び出しに失敗しました: AccessDeniedException」 | `kq-ec2-role` の `kq-invoke-agent` の ARN を確認（2行とも必要）。`kq-chat.env` の ARN も確認 |
| 「エラー（500）: AGENT_RUNTIME_ARN が設定されていません」 | 9-5 をやり直し、`sudo systemctl restart kq-chat` |
| 「MODEL_ID が設定されていません」 | 6-1 で `MODEL_ID` を書き、6-2 で zip を作り直し、エージェントの画面の **Update hosting**（ホスティングを更新）で新しい zip を指定する |
| 答えに「マニュアルを検索できませんでした（AccessDeniedException…）」 | 6-5 の `KB_ID`・`ACCOUNT_ID` を確認 |
| 答えに「managedSearchConfiguration」や「vectorSearchConfiguration」についてのエラー | `config.json` の `KB_TYPE` とナレッジベースの型が合っていない（Managed 型なら `managed`、昔ながらの型なら `custom`） |
| 検索しても何も出てこない | 4-2 の同期が終わっているか。S3 のファイルがバケットの一番上にあるか |
| 文書が読めない（権限がない） | 6-5 の `kq-docs-ACCOUNT_ID` の置き換えを確認。文書が `documents/` の中にあるか |
| ギルドAPIが呼べない | Lambda の名前が `kq-guild-api-mock` か。6-5 の Lambda の ARN を確認 |
| LLM を呼ぶところで `AccessDeniedException` / `ValidationException` | ① 2-4 のプレイグラウンドで1回呼んだか（初回の購読・Anthropic のフォーム）② モデルIDが東京から呼べる推論プロファイルIDか ③ 6-5 のポリシーが付いているか |
| エージェントの詳細を調べたい | **CloudWatch** → **Log groups**（ロググループ）で `/aws/bedrock-agentcore/runtimes/` で始まるものを見る。Lambda は `/aws/lambda/kq-guild-api-mock` |
| zip を上げたあと「No module named …」で動かない | zip を作り直す（6-2）。zip の一番上に `main.py` があるか。自分で zip にし直さず、`build_zip.py` が作ったものをそのまま使う |
| EC2 での貼り付けが崩れる | 9-2 の `export LANG=C.UTF-8` をしてから、9-3 をやり直す |

---

## 13. 片付け（削除の順番）

上から順に消します。ナレッジベースと EC2 は、置いておくだけで料金がかかることがあるので、必ず消してください。

1. ローカル: ポート転送とチャット画面を `Ctrl + C` で止める
2. **EC2**: `kq-chat-ec2` を選び **Instance state**（インスタンスの状態）→ **Terminate (delete) instance**（インスタンスを終了 (削除)）。終わったら、**Security Groups**（セキュリティグループ）で `kq-chat-sg` を削除
3. **IAM**: ユーザー `kq-chat-local` を削除（アクセスキーも一緒に消える）。ロール `kq-ec2-role` を削除。自分のPCの `aws configure --profile kq-chat` の設定も不要なら消す（`%USERPROFILE%\.aws\credentials` の `[kq-chat]` の部分）
4. **AgentCore Runtime**: `kq_agent` を削除（エンドポイントがあれば先に削除）。自動で作られた実行ロール（`AmazonBedrockAgentCoreRuntimeDefaultServiceRole-…`）も IAM で削除。zip の置き場所としてコンソールが自動で作った S3 バケット（`bedrock-agentcore-runtime-ACCOUNT_ID-ap-northeast-1-…`）も空にして削除
5. **ナレッジベース**: `kq-manual-kb` を削除。自動で作られたサービスロールも IAM で削除
6. **Lambda**: `kq-guild-api-mock` を削除。自動で作られた実行ロール（`kq-guild-api-mock-role-…`）も IAM で削除
7. **S3**: `kq-manual-ACCOUNT_ID` と `kq-docs-ACCOUNT_ID` を、**Empty**（空にする）→ **Delete**（削除）の順で消す
8. **CloudWatch Logs**: `/aws/bedrock-agentcore/runtimes/…` と `/aws/lambda/kq-guild-api-mock` のロググループを削除
9. 翌日以降に **Billing and Cost Management**（請求とコスト管理）で、料金が増え続けていないか確かめる

---

## 14. 本番に広げるときに変わる点

| 項目 | 今回（検証） | 本番の考え方 |
|------|-----------|------------|
| 入口 | ローカルPC → SSM のポート転送 | 商用サービス（仮。CRM・業務システムなど HTTP で呼べるものなら何でも）→ API Gateway → EC2 |
| 利用者の認証 | IAM ユーザーのアクセスキー（本人だけ） | API Gateway で OAuth 2.0 の認証（JWT オーソライザーなど）。商用サービス（仮）の側は、OAuth のトークンを付けて API Gateway を呼ぶ【要確認: 組み合わせ方は設計時に確認】 |
| EC2 の置き場所 | デフォルトVPC・パブリックIPあり・インバウンド0件 | プライベートサブネット。パブリックIPなし。API Gateway からは VPC リンクと内部のロードバランサー経由 |
| EC2 から AWS への通信 | パブリックIPでインターネット経由 | VPC エンドポイント（SSM 用の ssm・ssmmessages・ec2messages、AgentCore、CloudWatch Logs、S3 など）か NAT ゲートウェイ【要確認: AgentCore の VPC エンドポイントの対応】 |
| AgentCore の呼び出し | EC2 の IAM ロール | 同じでもよい。利用者ごとに分けるなら、利用者IDのヘッダー（`InvokeAgentRuntimeForUser` の権限が必要）や、Runtime 側の OAuth の受け付けを使う |
| 道具の呼び出し | エージェントが Lambda を直接呼ぶ | AgentCore Gateway で Lambda を MCP の道具として公開し、認可を一か所にまとめる |
| 外部API | 呼んだふり | 本物を呼ぶ。認証情報は Secrets Manager や AgentCore Identity で管理。タイムアウトと再試行を決める |
| マスタールール | プロンプトだけで断る | Bedrock Guardrails（拒否するトピックなど）も重ねる。ルールの版を管理する |
| 会話の記憶 | Runtime のメモリの中（セッションが切れると消える） | AgentCore Memory などに保存 |
| 監視 | CloudWatch Logs を手で見る | AgentCore Observability、アラーム、ダッシュボード |
| 配置の方法 | コンソールで zip を上げる | CI/CD（AgentCore CLI、CDK、CloudFormation など）で自動化 |
| EC2 | 1台・手作業で設定 | 複数のアベイラビリティーゾーン、Auto Scaling、設定済みの AMI やコンテナ |
| モデル | 未定（設定で指定） | 決めたモデルを固定し、使える量（クォータ）と料金を確認 |

---

## 15. 公式ドキュメントとの照合結果（報告）

書く前に公式ドキュメントで確かめました。依頼時の「確認できた事実」と照らした結果です。

### 15-1 依頼時の前提との照合

| # | 前提 | 結果 |
|---|------|------|
| 1 | Bedrock Agents（2023年11月提供）は Bedrock Agents Classic に改称し、2026-07-30 以降は新規のお客様は使えない | 一致 |
| 2 | Bedrock 本体・モデル・Knowledge Bases・Guardrails は影響なし | 一致 |
| 3 | 代わりは AgentCore | 一致 |
| 4 | Managed Knowledge Base は 2026-06-17 に GA | 一致（東京も対象） |
| 5 | ベクトルDBの運用が不要 | 一致 |
| 6 | Managed 型では RetrieveAndGenerate は使えない | 一致（API リファレンスに明記。Retrieve か AgenticRetrieveStream を使う） |
| 7 | 検索の設定は managedSearchConfiguration | 一致（件数 numberOfResults は 1〜100） |
| 8 | 昔作った Customer-managed 型はそのまま使え、設定は vectorSearchConfiguration | ほぼ一致。**公式の呼び名は「custom knowledge bases」**（API 上の種類は VECTOR） |
| 9 | Managed 型の料金は検証記事（2026-06-18時点）で固定費なし・使った分だけ | 一致。ただし公式の料金ページは「保存量」と「検索回数」に応じた料金と読めるため、置いておくだけでも保存量の分はかかる可能性がある【要確認】 |
| 10 | 呼び出しは boto3 の bedrock-agentcore クライアントの invoke_agent_runtime | 一致（セッションIDは33文字以上） |
| 11 | ローカルからの SSM 接続には Session Manager plugin が必要 | 一致 |
| 12 | プライベートサブネットの EC2 は NAT か VPC エンドポイントが必要 | 一致 |

食い違い（公式を優先したもの）は 8 の呼び名だけです。

### 15-2 前提になかったが、手順に反映した事実
- Managed 型ナレッジベースは、AgentCore の画面（今の表記では「コネクター」→「ナレッジベース (KB)」）から作る手順になっている（4章）
- AgentCore Runtime の zip は arm64 用の部品で作る必要がある。Windows の pip では正しく集められないため、公式と同じ uv を使う（6-2）
- Runtime の Python 3.10・3.11 は 2026-06-30 で非推奨。3.13 を使う（6-3）
- InvokeAgentRuntime の権限は、Runtime とその入口（エンドポイント）の両方に必要（7-2）
- Bedrock の「モデルアクセス」のページは廃止され、モデルは初回の呼び出しで使えるようになる。Anthropic の Claude Opus 4.7 より前のモデルは初回にフォームの提出が必要（2-4）
- Runtime の名前にハイフンは使えない（`kq_agent`）

### 15-3 要確認の一覧
1. AgentCore コンソールの画面の表記（Host agent の各項目、環境変数の欄があるか、Runtime ARN の表示場所、Test endpoint の表記）
2. Managed 型ナレッジベースの作成メニューの場所
3. ポート転送用ポリシーの書き方（AWS が用意したドキュメントの ARN の書き方、`ssm:SessionDocumentAccessCheck` の働き）
4. Amazon Linux 2023 の `python3.13` / `python3.13-pip` のパッケージ名
5. 東京で使えるモデルと推論プロファイルID、モデルごとの道具の呼び出しへの対応
6. Managed 型ナレッジベースの料金の内訳
7. `AWS-StartPortForwardingSession` が EC2 の中のどこ（localhost）につなぐか（127.0.0.1 で待ち受けてつながる前提で作っています）
8. （確認済み 2026-11-20）zip の置き場所としてコンソールが S3 バケット `bedrock-agentcore-runtime-…` を自動で作る
