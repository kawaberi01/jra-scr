# nankankeiba-pattern-analysis 前提メモ

## 目的

南関東4競馬場サイトの「勝ちパターン分析」を、AIによる勝ち馬分析の前処理データとして取得・構造化する。

ユーザー入力例:

```text
1R 2026年7月6日 第4回 川崎競馬 第1日
の勝ち馬分析より、勝ち馬を分析してください。
```

この入力から勝ちパターン分析URLを決定的に生成し、HTMLを取得し、馬ごとの評価材料としてJSON化する。

## 参照済み情報

- 公式ヘルプ: https://www.nankankeiba.com/info/qanda/help_kachipatan.html
- 実ページ例: https://www.nankankeiba.com/pattern_kis/202607062104010101.do
- 確認済みカテゴリURL:
  - `pattern_kis`: 騎手
  - `pattern_uma`: 出走馬
  - `pattern_cho`: 調教師
  - `pattern_kis_cho`: 騎手×調教師

## URL構造

勝ちパターン分析URL:

```text
https://www.nankankeiba.com/{category}/{race_pattern_id}.do
```

`race_pattern_id`:

```text
YYYYMMDD + nankan_course_code + meeting_no + meeting_day + race_no + period_code
```

例:

```text
202607062104010101
20260706 21 04 01 01 01
```

意味:

- `20260706`: 開催日
- `21`: 南関東サイト上の川崎コード
- `04`: 第4回
- `01`: 第1日
- `01`: 1R
- `01`: 分析期間

## 分析期間

ページ内JavaScript `patternLink(val)` はURL末尾2桁を差し替える。

- `01`: 生涯成績
- `02`: 直近1年
- `03`: 直近3ヶ月

## AI評価へ渡すべき原則

- HTMLを直接AIに渡さない。
- URL生成、HTML取得、テーブル解析、勝率数値化はプログラムで行う。
- AIには、馬ごとに統合済みの構造化JSONを渡す。
- 勝率だけでなく `(勝利数/母数)` を保持する。
- オッズ・人気は変動するため、取得時刻とsource URLを保持する。

## 未確定事項

- 浦和、船橋、大井の南関東サイト内コードは実ページ確認が必要。
- 出走取消、オッズ未提供、人気未確定時のHTML差分はfixture収集後に確定する。
- AI評価の重み付けは別機能とし、本仕様では取得・構造化までを主対象とする。
