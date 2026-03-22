# コントリビューション

このプロジェクトへの参加を歓迎します。  
実装者が人でも AI エージェントでも、レビュー可能で再現性のある変更であることを重視します。

## 基本方針

- ワークフローは GitHub Flow です。
- `main` への直接 push は行わず、PR 経由で変更します。
- 新機能や不具合修正には、対応するテストを追加します。
- `ruff` と `pytest` を通してから PR を出します。

## 開発セットアップ

```bash
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge
uv sync --dev
make setup
```

`make setup` は git hook を有効化するため必須です。

## 確認コマンド

```bash
uv run ruff check claude_discord/
uv run ruff format --check claude_discord/
uv run pytest tests/ -v --cov=claude_discord
```

## ブランチ命名

- `feature/description`
- `fix/description`
- `docs/description`
- `refactor/description`

## 詳細ガイド

日本語の詳細版は [docs/07_コントリビューションガイド.md](/mnt/d/develop/ai-dev-discord-bridge/docs/07_コントリビューションガイド.md) を参照してください。
