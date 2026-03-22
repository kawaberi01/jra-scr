# claude-code-discord-bridge (ccdb)

Claude Code CLI のための Discord フロントエンドです。  
**これは個人用 Bot ではなく、フレームワーク（OSS ライブラリ）です。**

**略称: ccdb** (`claude-code-discord-bridge`)

## フレームワークと個別インスタンス

- **claude-code-discord-bridge**（このリポジトリ）は、再利用可能な OSS フレームワークです。個人設定、秘密情報、サーバー固有ロジックは持ち込みません。
- 個別の運用例（例: EbiBot）は、custom Cog loader (`CUSTOM_COGS_DIR` / `--cogs-dir`) を使って独自 Cog を追加します。参考実装は `examples/ebibot/` にあります。
- 機能追加時は、「誰にでも有用ならここに入れる」「個人運用だけなら custom Cog に出す」を原則にします。

### Zero-Config 原則（重要）

**利用者は、パッケージを更新するだけで新機能を受け取れるべきです。コード変更を要求してはいけません。**

- 新機能は基本的にデフォルト有効、または自然なデフォルト値を持つべきです。
- 新しいコンストラクタ引数には後方互換なデフォルト値 (`= None` など) を付けます。
- 利用者に追加配線を要求する設計は誤りです。ccdb 側で吸収します。
- 利用者が ccdb の Cog をコピー、ラップ、継承しないと拡張できないなら、その時点で拡張ポイントが不足しています。

## アーキテクチャ

- **Python 3.10+** と `discord.py v2`
- 機能ごとの **Cog パターン**
- データアクセスの **Repository パターン**（SQLite + `aiosqlite`）
- Claude Code CLI 呼び出しには **`asyncio.subprocess`** を使う（`shell=True` は使わない）

## 主要な設計判断

1. **API ではなく CLI を起動する**  
   `claude -p --output-format stream-json` をサブプロセスとして呼び出します。これにより `CLAUDE.md`、skills、tools、memory などの Claude Code 機能をそのまま活用できます。
2. **Thread = Session**  
   Discord の各スレッドは Claude Code の 1 セッションに 1:1 で対応します。スレッドへの返信は `--resume` で同一セッションを継続します。
3. **進行状態は絵文字リアクションで示す**  
   非侵襲で分かりやすく、Discord のレート制限にも比較的強い方法です。
4. **コードフェンスを壊さない分割**  
   Discord の文字数制限でもコードブロックを破壊しないように分割します。
5. **インストール可能な Python パッケージとして提供する**  
   利用者は `uv add git+...` や `pip install git+...` で導入し、ファイルをコピーして使う前提ではありません。
6. **共通 run helper を持つ**  
   `cogs/_run_helper.py` が、`ClaudeChatCog` と `SkillCommandCog` の共通実行ロジックを担います。
7. **REST API を制御プレーンとして使う**  
   Claude Code サブプロセスは stdout マーカーではなく REST API (`CCDB_API_URL`) で ccdb に戻ってきます。明示的で、外部システムからも利用しやすい構成です。
8. **SQLite ベースの動的スケジューラ**  
   定期タスクは DB に保存し、1 本の `discord.ext.tasks` マスターループが実行します。タスク追加のためにコード変更は不要です。
9. **Claude が「何をするか」を決め、ccdb は「いつ実行するか」を決める**  
   スケジュールタスクでも、ドメインロジックは Claude の prompt 側に置き、ccdb 側に GitHub 固有 / Azure 固有ロジックを入れません。

### Claude → ccdb 連携で stdout マーカーではなく REST API を選ぶ理由

検討した代替案:
- Claude が `<!-- ccdb:schedule {...} -->` のようなマーカーを出力し、ccdb が stdout から拾う

不採用理由:
- テキスト解析が壊れやすい
- テストしづらい
- 外部システムから使えない
- 出力テキストに副作用を埋め込む設計になる

REST API を採用した理由:
- インターフェースが明示的
- 独立してテストしやすい
- GitHub Actions などの外部からも使える
- すでに `ext/api_server.py` という土台がある

## 開発

### セットアップ

```bash
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge
uv sync --dev
```

### テスト実行

```bash
uv run pytest tests/ -v --cov=claude_discord
```

PR を出す前に、すべてのテストを通してください。CI は Python 3.10 / 3.11 / 3.12 で動きます。

### Lint / Format

```bash
uv run ruff check claude_discord/
uv run ruff format claude_discord/
```

CI では `ruff check` と `ruff format --check` の両方が必須です。

### 単体起動

```bash
cp .env.example .env
# .env に Discord Bot token と channel ID を設定
uv run python -m claude_discord.main
```

### EbiBot のデプロイに関する注意

「手動で `git pull` が必要」「`systemctl restart` が必要」と決めつける前に、  
`scripts/pre-start.sh`、`.github/workflows/`、`examples/ebibot/cogs/` を確認してください。  
すでに自動化されている可能性があります。

### 開発フロー（worktree + ローカルテスト）

EbiBot は `/home/ebi/claude-code-discord-bridge/` から直接起動します。  
PR マージ前に EbiBot で実機確認するため、**dev worktree モード** が用意されています。

```bash
# 1. worktree を作ってブランチで作業
git worktree add ../wt-my-feature -b feat/my-feature

# 2. worktree で実装・ユニットテスト
cd /home/ebi/wt-my-feature
uv run pytest tests/ -v

# 3. dev mode を有効化して Discord 上で確認
make dev-on

# 4. 確認完了後に dev mode を解除して PR 作成
make dev-off
make pr
```

**仕組み (`pre-start.sh`)**

1. `uv sync` 後、`_ccdb_dev_hook.py` と `_ccdb_dev_hook.pth` を venv の `site-packages` に配置する
2. `.pth` により Python 起動時に `_ccdb_dev_hook` を import する
3. `_ccdb_dev_hook.py` が `sys.meta_path[0]` に `_Finder` を挿入する
4. `_Finder` が `~/.ccdb-dev-worktree` を読み、`claude_discord` import を worktree 側へ差し替える

`.pth` / `PYTHONPATH` / `sitecustomize.py` では CWD 優先を上書けないため、この方式を採用しています。

**通常起動（本番モード）**

`~/.ccdb-dev-worktree` がなければフックは何もしません。  
main ブランチで差分がなければ、`pre-start.sh` が `git pull` して最新コードを取得します。

## コード規約

### スタイル

- **Formatter / Linter**: `ruff`（設定は `pyproject.toml`）
- **型ヒント**: すべての関数シグネチャに必須
- **Python**: 3.10+、各ファイルで `from __future__ import annotations` を使う
- **行長**: 100 文字まで
- **import**: `ruff` の `I` ルールに従って整列。型専用 import は `TYPE_CHECKING` に入れる

### エラー処理

- Discord API 呼び出しで失敗しうる箇所は `contextlib.suppress(discord.HTTPException)` を使う
- 業務ロジックで例外を黙殺しない
- CLI サブプロセスエラーは、例外をそのまま投げるより `StreamEvent.error` に変換して表現する

### セキュリティ（重要）

このプロジェクトは任意の Claude Code セッションを実行します。  
セキュリティは妥協不可です。

**コミット前に必ず確認すること**

- `create_subprocess_exec` を使い、`shell=True` を使わない
- prompt の前に `--` を置いてフラグ注入を防ぐ
- `--resume` に渡す前に session ID を厳密に検証する
- skill 名を厳密に検証する
- `DISCORD_BOT_TOKEN` などの秘密情報をサブプロセスに渡さない
- `dangerously_skip_permissions` をデフォルト有効にしない

`runner.py`、`_run_helper.py`、各 Cog を変更した場合は、セキュリティ監査を必須とします。

### 命名

- ファイル: `snake_case.py`
- クラス: `PascalCase`
- 関数 / メソッド: `snake_case`
- 非公開要素: 先頭に `_`
- 定数: `UPPER_SNAKE_CASE`

### テスト（TDD 前提）

**新機能や不具合修正は、必ず TDD で進めます。**

1. **RED**: 先に失敗するテストを書く
2. **GREEN**: 最小の実装で通す
3. **REFACTOR**: テストが緑のまま整理する
4. **VERIFY**: `ruff` と `pytest` を通す

```bash
uv run ruff check claude_discord/
uv run pytest tests/ -v --cov=claude_discord
```

## プロジェクト構成

```text
claude_discord/          # インストール可能な Python パッケージ
  __init__.py            # 公開 API
  cli.py                 # CLI エントリポイント
  main.py                # 単体起動の入口
  setup.py               # setup_bridge()
  cog_loader.py          # custom Cog ローダー
  bot.py                 # Discord Bot クラス
  protocols.py           # 共通 protocol
  concurrency.py         # 並行実行制御
  lounge.py              # AI Lounge prompt builder
  session_sync.py        # CLI セッション同期
  worktree.py            # WorktreeManager
  cogs/                  # Discord Cogs
  claude/                # CLI 実行・パース関連
  database/              # SQLite 永続化
  discord_ui/            # Discord 表示部品
  ext/                   # 拡張 API サーバー
  utils/                 # ログなどの補助
tests/                   # pytest テスト
examples/                # 実運用例
pyproject.toml           # パッケージ設定
uv.lock                  # lock file
CONTRIBUTING.md          # 参加ガイド
```

### 新しい Cog を追加する手順

1. `claude_discord/cogs/your_cog.py` を作る
2. Claude CLI を使うなら `_run_helper.run_claude_in_thread()` を使い、ストリーミング処理を重複実装しない
3. `claude_discord/cogs/__init__.py` から export する
4. `claude_discord/__init__.py` の公開 API に追加する
5. `tests/test_your_cog.py` を書く

### custom Cog の読み込み規約

`cog_loader.py` は `CUSTOM_COGS_DIR` または `--cogs-dir` で指定されたディレクトリから `.py` を読み込みます。  
各ファイルは次を export する必要があります。

```python
async def setup(bot, runner, components):
    await bot.add_cog(MyCog(bot))
```

ルール:
- `_` で始まるファイルは読み込まない
- 読み込み順は `sorted()` で安定化
- 1 つの Cog が失敗しても他を止めない
- `examples/ebibot/cogs/` を参照実装とする

### 新しい Discord UI コンポーネントを追加する手順

1. `claude_discord/discord_ui/` の適切なファイルに追加する
2. 公開 API が必要なら `__init__.py` から export する
3. 空文字列、長文、Unicode、コードブロックなどの境界条件をテストする

## Git / PR ワークフロー

- `main` からブランチを切る
- CI を必ず通す
- `main` へ直接 push しない
- squash merge を推奨する
- コミットメッセージは `<type>: <description>` 形式を推奨する

## AI エージェント設定

このプロジェクトは複数の AI ツール向け設定を持っています。

| ファイル | ツール | 用途 |
|----------|--------|------|
| `CLAUDE.md` | Claude Code | プロジェクト文脈 |
| `AGENTS.md` | OpenAI Codex | `CLAUDE.md` へのリンク |
| `.github/copilot-instructions.md` | GitHub Copilot | 短縮版指示 |
| `.cursorrules` | Cursor | IDE 向けルール |

### Skills (`.claude/skills/`)

| Skill | 用途 |
|-------|------|
| `tdd` | TDD を強制する |
| `verify` | コミット前の品質確認 |
| `add-cog` | 新規 Cog 作成手順 |
| `security-audit` | サブプロセス / 注入系の監査 |
| `python-quality` | Python 品質基準 |
| `test-guide` | テストパターン |

### Commands (`.claude/commands/`)

| Command | 用途 |
|---------|------|
| `/verify` | 検証パイプライン実行 |
| `/new-cog <name>` | 新しい Cog の雛形作成 |

### Hooks (`.claude/settings.json`)

- `Edit/Write` 後に `.py` を `ruff` で自動整形する

## ここに入れてはいけないもの

- 個人用 Bot の設定（token、channel ID、user ID など）
- サーバー固有の Cog やワークフロー
- Anthropic API への直接呼び出し
- 大多数の利用者に不要な重い依存関係
- パッケージ import 時に秘密情報を要求する設計
