# 南関東 勝ちパターン分析 利用ガイド

## 概要

南関東4競馬場サイトの「勝ちパターン分析」を取得し、AI評価や後続処理で使いやすい JSON に整形する機能です。

現時点の最小実装条件:

- 対象場は `kawasaki` のみ
- 対応 period は `lifetime` または `01` のみ
- 取得カテゴリは `pattern_kis`, `pattern_uma`, `pattern_cho`, `pattern_kis_cho`

## CLI

### 標準出力へ JSON を出す

```bash
rtk uv run jra-srb fetch-nankankeiba-pattern \
  --date 2026-07-06 \
  --course kawasaki \
  --meeting 4 \
  --day 1 \
  --race 1
```

### ファイルへ保存する

```bash
rtk uv run jra-srb fetch-nankankeiba-pattern \
  --date 2026-07-06 \
  --course kawasaki \
  --meeting 4 \
  --day 1 \
  --race 1 \
  --output data/nankankeiba_pattern_20260706_kawasaki_1r.json
```

### 任意指定

```bash
rtk uv run jra-srb fetch-nankankeiba-pattern \
  --date 2026-07-06 \
  --course kawasaki \
  --meeting 4 \
  --day 1 \
  --race 1 \
  --periods lifetime \
  --categories pattern_kis,pattern_uma,pattern_cho,pattern_kis_cho
```

### 引数

- `--date`: 開催日。例 `2026-07-06`
- `--course`: 開催場。現時点では `kawasaki` のみ
- `--meeting`: 開催回。例 `4`
- `--day`: 開催日数。例 `1`
- `--race`: レース番号。例 `1`
- `--periods`: 期間。現時点では `lifetime` または `01`
- `--categories`: 取得カテゴリのカンマ区切り指定
- `--output`: 出力ファイル。未指定なら標準出力

## API

### エンドポイント

```http
GET /nankankeiba/pattern/meetings/{date}/{course}/races/{race_no}
```

### 必須クエリ

- `meeting_no`
- `meeting_day`

### 任意クエリ

- `periods`
- `categories`

### 例

```bash
curl "http://127.0.0.1:8000/nankankeiba/pattern/meetings/2026-07-06/kawasaki/races/1?meeting_no=4&meeting_day=1"
```

カテゴリを明示する例:

```bash
curl "http://127.0.0.1:8000/nankankeiba/pattern/meetings/2026-07-06/kawasaki/races/1?meeting_no=4&meeting_day=1&periods=lifetime&categories=pattern_kis,pattern_uma"
```

## レスポンス概要

レスポンスは馬ごとに4カテゴリを統合した JSON です。

主な項目:

- `race_id`
- `date`
- `course`
- `meeting_no`
- `meeting_day`
- `race_no`
- `periods`
- `categories`
- `runners`

`runners` の各要素には以下が入ります。

- `horse_no`
- `horse_name`
- `jockey`
- `trainer`
- `categories`

`categories` の中に、カテゴリ別の勝率情報が入ります。

代表的な rate key:

- `lifetime`
- `urawa`
- `funabashi`
- `oi`
- `kawasaki`
- `short`
- `medium`
- `long`
- `popularity_1`
- `popularity_2`
- `popularity_3`
- `popularity_4_or_more`

各 rate は以下の形です。

```json
{
  "rate": 14.5,
  "wins": 256,
  "starts": 1770
}
```

## race_id の考え方

内部では以下の16桁 race_id を組み立てます。

```text
YYYYMMDD + course_code(2桁) + meeting_no(2桁) + meeting_day(2桁) + race_no(2桁) + period(2桁)
```

例:

```text
2026-07-06 / kawasaki / 4回 / 1日目 / 1R / 01
=> 202607062104010101
```

## 注意点

- 公式サイト依存のため、HTML 構造変更時は parser の修正が必要です。
- オッズや人気は取得時点依存です。
- HTML 断片はレスポンスへ含めず、構造化済みデータのみ返します。
- 現時点では全場対応ではありません。川崎以外を前提に使わないでください。

## 実装位置

- [cli.py](/D:/develop/jra-scr/src/jra_srb/cli.py)
- [app.py](/D:/develop/jra-scr/src/jra_srb/app.py)
- [nankankeiba_pattern_service.py](/D:/develop/jra-scr/src/jra_srb/nankankeiba_pattern_service.py)
- [nankankeiba_pattern_extractors.py](/D:/develop/jra-scr/src/jra_srb/nankankeiba_pattern_extractors.py)
