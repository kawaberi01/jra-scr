"""概要: rawの全4資料を条件台帳にし、原文の用途でマイルCS過去成績を検証する。
作成日: 2026-11-22
入力: --output 新規保存先。raw全資料、固定国内履歴、GI公式成績、当日保存入力。
出力: 原文/SHA、全主張台帳、条件別四区分と明細、用途別順位比較、今年の該当。
実行例: uv run python scripts/audit_mile_raw_materials.py --output artifacts/jra_research/mile_raw_audit_20261122_v1
注意事項: 探索的診断。原動画は未確認。結果API・DB書込み・旧予想変更・実購入なし。
"""

import argparse
from collections import defaultdict
from datetime import date
import hashlib
import json
from pathlib import Path
import sys
import unicodedata
import re
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
from jra_srb.jra_mile_rule_integration import counts, expression, features, turf
from jra_srb.jra_specific_patterns import route_name
from jra_srb.jra_race_conditions import require
from run_jra_graded_live import table
from run_jra_mile_rule_integration import read, save

# 複合条件の構成要素は親の一体条件へ対応させ、別の独立支持数を作らない。
RULES = [
    ("age34", "3歳または4歳", "positive", "all"),
    ("previous5", "前走5着以内", "positive", "all"),
    ("pop5", "当日5番人気以内", "positive", "all"),
    ("pop6", "当日6番人気以内", "positive", "all"),
    ("route4", "前走が指定4重賞", "positive", "all"),
    ("fuji2", "前走富士S2着以内", "positive", "all"),
    ("outer", "京都開催の7・8枠", "positive", "kyoto"),
    ("frame5", "京都開催の5枠", "negative", "kyoto"),
    ("mile_g1_top2", "収録内に芝1600mGI連対実績", "positive", "all"),
    ("age7", "7歳以上", "negative", "all"),
    ("swan", "前走スワンS", "negative", "all"),
    ("kyoto1600_top3", "収録内に京都芝1600m3着以内", "positive", "all"),
    ("kyoto1600_graded_win", "収録内に京都芝1600m重賞勝利", "positive", "all"),
    ("female_no_mixed_win", "牝馬かつ当年国内混合GI/GII勝利を収録内確認できない", "negative", "all"),
    ("previous_domestic6", "実前走が国内で6着以下", "negative", "all"),
    ("sameyear_sekiya_chukyo", "当年関屋記念または中京記念へ出走", "negative", "all"),
    ("previous_not_tokyo_nakayama", "実前走が東京・中山以外", "negative", "all"),
    ("age6_no_fuji2", "6歳以上かつ前走富士S2着以内ではない", "negative", "all"),
    ("age3_nhk", "3歳かつNHKマイルC出走経験を収録内確認", "negative", "all"),
    ("sameyear_nakayama1600", "当年中山芝1600m重賞へ出走", "negative", "all"),
    ("specified_g1_win5_male6", "国内マイルCS/安田/朝日杯を当時5番人気以内で勝利、6歳以下牡セン", "positive", "all"),
    ("outer_price", "京都7・8枠かつ当日単勝19.9倍以下", "positive", "kyoto"),
    ("last_win_g2", "前走1着かつ前走GII（生産者救済の一部のみ）", "positive", "all"),
    ("last_win_g2_parent", "前走東京/中山以外の群で、前走GII1着（生産者条件なし）", "positive", "all"),
    ("right_experience", "収録内に右回り出走経験", "positive", "all"),
    ("mile_top3", "収録内に芝1600m3着以内", "positive", "all"),
    ("layoff113", "実前走から113日以上（休み明けの代理定義）", "negative", "all"),
    ("four_main", "年齢3/4・前走5着内・人気5位内・指定4重賞の全一致", "positive", "all"),
    ("g2_breeder_rescue", "前走東京/中山以外、前走GII1着、社台系4牧場の暫定救済", "positive", "all"),
    ("outside_after_breeder_rescue", "前走東京/中山以外で上記救済に非該当", "negative", "all"),
]


def norm(value):
    """表記揺れ比較用にNFKCと空白除去を行う。"""
    return "".join(unicodedata.normalize("NFKC", str(value or "")).split())


def conjunction(*args):
    """欠測を保持した論理積を評価する。"""
    return expression({"op": "and", "children": [{"atom": str(i)} for i in range(len(args))]}, {str(i): v for i, v in enumerate(args)})


def fact_for(row, link_map, fact_map):
    """馬名結合をせず、確認済み競走ID/馬IDのリンクから公式値を取る。"""
    linked = link_map.get((row.get("race_key"), row["horse_id"]))
    return fact_map[linked] if linked else None


def rule_features(race, runner, history, foreign, link_map, fact_map, current_observation=None, breeders=None):
    """対象日前の同じ過去走へ格/着順/人気を結び、原資料の条件を判定する。"""
    f = features(race, runner, history, foreign)
    prior = [h for h in history if h["horse_id"] == runner["horse_id"] and h["race_date"] < race["race_date"] and h["status"] == "active"]
    sameyear = [h for h in prior if h["race_date"][:4] == race["race_date"][:4]]
    previous = f["references"]["previous"]
    route = route_name(previous.get("race_name") or previous.get("race_name_raw") or "") if previous else None
    ownfact = fact_for({**runner, "race_key": race["race_key"]}, link_map, fact_map) if current_observation is None else None
    observed = current_observation if current_observation is not None else ownfact["values"] if ownfact else {}
    pop, odds = observed.get("popularity"), observed.get("win_odds")
    pop = int(pop) if pop is not None else None
    odds = float(odds) if odds is not None else None
    age, sex = runner.get("age"), runner.get("sex")
    has_age = type(age) is int
    rank = previous.get("rank") if previous else None
    valid_rank = type(rank) is int and rank > 0
    g1_wins = [h for h in prior if h.get("grade") == "A" and h.get("distance") == 1600 and turf(h) and h.get("rank") == 1
               and norm(h.get("race_name")) in {"マイルチャンピオンシップ", "マイルチャンピオンS", "安田記念", "朝日杯フューチュリティステークス", "朝日杯FS"}]
    qualified, missing_g1_pop = [], []
    for h in g1_wins:
        fact = fact_for(h, link_map, fact_map)
        p = fact["values"].get("popularity") if fact else None
        if p is None:
            missing_g1_pop.append(h)
        elif int(p) <= 5:
            qualified.append({"past_run": h, "fact_record_id": fact["record_id"], "popularity": p})
    g1_flag = True if qualified else None if missing_g1_pop or not prior else False
    mixed_wins = [h for h in sameyear if h.get("rank") == 1 and h.get("grade") in ("A", "B") and len(h.get("symbol") or "") == 3 and h["symbol"][1] == "0"]
    mixed_missing = any(h.get("rank") == 1 and h.get("grade") in ("A", "B") and len(h.get("symbol") or "") != 3 for h in sameyear)
    mixed_flag = bool(mixed_wins) if prior and not mixed_missing else True if mixed_wins else None
    values = {k: f["atoms"][k] for k in ("age34", "previous5", "route4", "mile_g1_top2", "kyoto1600_top3")}
    fuji2 = f["atoms"]["fuji_top2"]
    values.update({
        "pop5": pop <= 5 if pop else None, "pop6": pop <= 6 if pop else None,
        "fuji2": fuji2, "outer": runner.get("frame_no") in (7, 8) if runner.get("frame_no") else None,
        "frame5": runner.get("frame_no") == 5 if runner.get("frame_no") else None,
        "age7": age >= 7 if has_age else None, "swan": route == "スワンS" if previous else None,
        "kyoto1600_graded_win": any(h.get("venue_code") == "08" and h.get("distance") == 1600 and turf(h) and h.get("grade") in ("A", "B", "C") and h.get("rank") == 1 for h in prior) if prior else None,
        "female_no_mixed_win": conjunction(sex == "2" if sex is not None else None, not mixed_flag if mixed_flag is not None else None),
        "previous_domestic6": conjunction(not previous.get("foreign") if previous else None, rank >= 6 if valid_rank else None),
        "sameyear_sekiya_chukyo": any(norm(h.get("race_name")) in ("関屋記念", "中京記念", "トヨタ賞中京記念") for h in sameyear) if prior else None,
        "previous_not_tokyo_nakayama": (previous.get("venue_code") not in ("05", "06")) if previous and (previous.get("venue_code") or previous.get("foreign")) else None,
        "age6_no_fuji2": conjunction(age >= 6 if has_age else None, not fuji2 if fuji2 is not None else None),
        "age3_nhk": conjunction(age == 3 if has_age else None, any(norm(h.get("race_name")) in ("NHKマイルカップ", "NHKマイルC") for h in prior) if prior else None),
        "sameyear_nakayama1600": any(h.get("venue_code") == "06" and h.get("distance") == 1600 and turf(h) and h.get("grade") in ("A", "B", "C") for h in sameyear) if prior else None,
        "specified_g1_win5_male6": conjunction(g1_flag, age <= 6 if has_age else None, sex in ("1", "3") if sex else None),
        "last_win_g2": conjunction(rank == 1 if valid_rank else None, (previous.get("grade") == "B" or previous.get("international_grade_raw") == "GII") if previous else None),
        "right_experience": any(h.get("venue_code") in ("01", "02", "03", "06", "08", "09", "10") for h in prior) if prior else None,
        "mile_top3": any(turf(h) and h.get("distance") == 1600 and type(h.get("rank")) is int and 0 < h["rank"] <= 3 for h in prior) if prior else None,
        "layoff113": (date.fromisoformat(race["race_date"])-date.fromisoformat(previous["race_date"])).days >= 113 if previous else None,
    })
    values["outer_price"] = conjunction(values["outer"], odds <= 19.9 if odds is not None else None)
    values["last_win_g2_parent"] = conjunction(values["previous_not_tokyo_nakayama"], values["last_win_g2"])
    values["four_main"] = conjunction(*(values[k] for k in ("age34", "previous5", "pop5", "route4")))
    breeder = (breeders or {}).get(runner["horse_id"])
    breeder_flag = norm(breeder["breeder"]) in {"社台ファーム", "ノーザンファーム", "追分ファーム", "白老ファーム", "社台コーポレーション白老ファーム", "(有)社台コーポレーション白老ファーム"} if breeder else None
    values["g2_breeder_rescue"] = conjunction(values["last_win_g2_parent"], breeder_flag)
    values["outside_after_breeder_rescue"] = conjunction(values["previous_not_tokyo_nakayama"], not values["g2_breeder_rescue"] if values["g2_breeder_rescue"] is not None else None)
    require(set(values) == {r[0] for r in RULES}, "raw_audit_rule_keys")
    return {"conditions": values, "previous": previous, "base_atoms": f, "qualified_g1_wins": qualified, "missing_g1_popularity": missing_g1_pop,
        "sameyear_mixed_wins": mixed_wins, "sameyear_references": sameyear, "target_observed_popularity": pop, "target_observed_win_odds": odds,
        "target_fact_id": ownfact["record_id"] if ownfact else None, "breeder_observation": breeder,
        "coverage_note": "否定の実績は保存国内履歴内の確認なし。歴年海外欠落、当日市場は歴年最終値と今年途中値の差あり。社台系は暫定4牧場"}


def catalogue():
    """全4資料の各着眼点・救済・第三者意見を漏れなく台帳へ対応付ける。"""
    rows = []
    def add(file, text, rule=None, reason=None, kind="condition"):
        """一つの主張を規則または保留理由に接続する。"""
        rows.append({"id": f"claim-{len(rows)+1:03d}", "file": file, "claim": text, "rule_id": rule,
            "status": "再集計対象" if rule else "意見として保存" if kind == "opinion" else "定義/データ待ち", "reason": reason, "kind": kind})
    m1, m2, m3, slow = "MC条件1.txt", "MC条件2.txt", "MC条件3.txt", "MC条件ゆっくり.txt"
    for text, rule in (("マイルG1実績", "mile_g1_top2"), ("年齢", "age34"), ("人気", "pop6"), ("7歳以上", "age7"), ("枠順", "outer"), ("5枠", "frame5"), ("コース実績", "kyoto1600_top3")):
        add(m1, text, rule)
    for text, reason in (("末脚の持続力", "個馬の残り800m持続計測/閾値が未定義。既存Fは同義ではない"), ("脚質", "差しの分類と判定時点が不明。今回レースの事後位置を事前入力にしない"),
        ("斤量", "利点の量と条件が未定義。既存Wの相対斤量とは別"), ("展開", "ペース/仕掛けのシナリオ定義が必要"), ("騎手", "相性の対象期間/母集団/閾値が未定義"),
        ("近走成績", "既存N/Cと距離変更は再利用可。ただし資料の総合評価規則は不明"), ("状態", "休養代理は別集計。季節/仕上がりの観測と定義が不足")):
        add(m1, text, reason=reason)
    add(m1, "休み明け", "layoff113", reason="113日以上は既存区分による代理で動画の明示閾値ではない")
    add(m1, "推奨5頭とロデオドライブ本命", reason="能力の実証済み事実ではなく第三者の総合判断。持続力が未定義", kind="opinion")
    for text, rule in (("①3歳または4歳", "age34"), ("②前走5着以内", "previous5"), ("③当日5番人気以内", "pop5"), ("④前走が指定の4重賞", "route4"),
        ("富士Sで2着以内", "fuji2"), ("7・8枠", "outer"), ("マイルG1での連対実績", "mile_g1_top2"), ("7歳以上は割引", "age7"), ("スワンSからの出走", "swan"), ("主要4条件の同時該当", "four_main")):
        add(m2, text, rule)
    add(m2, "差し・追い込み脚質", reason="過去10年の脚質定義が未提示。事後分類と事前適性を区別")
    add(m2, "当日の馬体重・パドック", reason="馬体重は公表後取得可能。パドックの構造化/評価基準なし")
    add(m2, "当日の馬場・オッズ", reason="現在値の取得と価格比較は可能。馬場適性/券種確率の計算規則は未提示")
    for text, rule in (("1 牝馬・当年混合G2以上未勝利", "female_no_mixed_win"), ("3 前走国内6着以下（救済前）", "previous_domestic6"),
        ("4 当年関屋/中京記念出走", "sameyear_sekiya_chukyo"), ("5 前走東京/中山以外（救済前）", "previous_not_tokyo_nakayama"),
        ("6 高齢・富士好走例外", "age6_no_fuji2"), ("7 前走スワンS", "swan"), ("8 3歳NHK経験", "age3_nhk"), ("9 当年中山マイル重賞", "sameyear_nakayama1600"),
        ("10〜12 指定国内GIを当時人気5位内で勝利＋6歳以下牡セン", "specified_g1_win5_male6"), ("13 京都7〜8枠", "outer"), ("14 外枠かつ19.9倍以下", "outer_price"),
        ("京都適性・重賞勝利", "kyoto1600_graded_win"), ("右回り適性・出走経験", "right_experience")):
        add(m3, text, rule)
    for text, reason in (("2 指定日本人騎手", "指定リスト未提供"), ("3 救済：富士/毎日王冠＋前走5番人気＋関西", "一部前走人気は公式GI値にあるが、全前哨戦と歴年所属の接続が不足。親群のみ別集計"),
        ("15 ロードカナロア産駒と2026年G1複勝率", "今年の父は取得可。全2026GI出走の父ID/母集団と集計締切が未監査。60%は未確認"),
        ("蹄の状態", "時点付き診断/観測なし"), ("調教内容", "コース調教/状態の時点付き構造化データ未接続"), ("展開適性", "ペースシナリオと先行判定の基準が未提示"),
        ("末脚", "既存Fの近GI上がり順位は計算済みだが、資料の速さの閾値は不明"), ("騎手", "京都外1600の母集団/期間/閾値が未定義"),
        ("海外馬の適性", "日本遠征/多頭数経験を確認する全海外履歴が不足"), ("血統適性", "父の取得と適性の実証は別。歴年網羅と評価式が不足"),
        ("人気・オッズ", "価格取得可能。人気薄を採用する最終規則は未提示")):
        add(m3, text, reason=reason)
    add(m3, "5 救済：前走1着＋G2＋社台系生産", "g2_breeder_rescue", reason="京都直近対象6頭を一次資料で補完。社台系は暫定4牧場。他年欠測は不明")
    add(m3, "5 救済後に残る割引群", "outside_after_breeder_rescue", reason="救済不明は割引確定にしない")
    add(m3, "救済の前走1着・G2部分", "last_win_g2", reason="生産者抜きの部分条件であり完全救済の代用にはしない")
    add(m3, "親群内の前走1着・G2部分", "last_win_g2_parent", reason="同上。親消去の文脈だけ合わせる")
    add(m3, "オフトレイルをスワン消去の例外として評価", reason="例外を定義する客観条件がなく第三者意見として保存", kind="opinion")
    slow_parts = [
        ("①開催週・コース替わり", "開催8週/Cコースは資料の主張。開催日程/コース使用の時点付きDB未接続"),
        ("②内外の有利不利", "外が伸びるという観測の対象レース/進路/能力補正が未定義。外枠好成績とは別"),
        ("③天候・馬場状態", "当日良表示は保存済み。乾燥度と適性補正は未接続"),
        ("④季節・芝の種類", "秋冬洋芝という主張と馬別適性の数値根拠は未確認"),
        ("⑤コース形態", "京都芝外1600の同定可。下り坂を使う個馬補正は未実装"),
        ("⑥スパート適性", "残り800mの個馬持続計測と評価閾値がない"),
        ("⑦過去のラップ傾向", "公式区間ラップの研究素材は利用可。今回はラップ→ペース分類規則が未提示"),
        ("⑧逃げ・先行馬の構成", "近走通過順位は今年カードから取得可。先行馬の分類/距離差補正が未定義"),
        ("⑨想定ペース", "平均ペースの定義と構成からの推定規則が未提示"),
        ("⑩脚質・末脚", "近走通過と既存Fは利用可。追走力/脚質自在性との同一視は不可"),
        ("⑪距離適性", "芝1600好走を代理として別集計。1400向きとの比較規則は未提示"),
        ("⑫過去レースの内容", "時計差P/Fは既存研究可。馬場/展開の恩恵を因果分離する基準なし"),
        ("⑬枠順・進路", "外枠と人気条件は別集計。内枠の馬群リスクを位置だけで断定しない"),
        ("⑭ローテーション・状態", "前走/休養は再利用可。仕上がりは観測不足"),
        ("⑮斤量・血統・騎手", "Wは既存計算可。3歳牝馬の有利幅、血統/騎手の重みは未定義"),
    ]
    for text, reason in slow_parts:
        add(slow, text, reason=reason)
    add(slow, "距離適性の代理：芝1600好走", "mile_top3", reason="動画の能力判断を再現したものではなく代理定義")
    add(slow, "枠の代理：京都7/8枠", "outer", reason="外伸び馬場そのものの検証ではない")
    for name, reason in (("ガイアフォース", "自在性/安定性"), ("スターアニス", "追走/末脚/斤量"), ("アンパドゥ", "外枠/末脚/ローテ"),
        ("ウォーターリヒト", "冬芝/差し"), ("スズハローム", "京都/末脚"), ("エンブロイダリー", "冬芝/内枠による消去"),
        ("ワールズエンド", "展開/距離/馬場による消去"), ("アドマイヤズーム", "馬場恩恵の評価"), ("オフトレイル", "1600能力低下")):
        add(slow, name+"の採否", reason=reason+"は資料の意見。測定定義がなく検証済み消去にしない", kind="opinion")
    return rows


def current_profile_facts(card):
    """保存済み公式プロフィールから今年の父/生産者を読み、過去所属へ流用しない。"""
    output = []
    folder = ROOT/"artifacts/jra_research/graded_2026_inputs_20261120_audit/mile/profiles"
    for runner in card["runners"]:
        path = folder/(runner["horse_id"]+".html")
        raw = path.read_bytes()
        soup = BeautifulSoup(raw.decode("utf-8"), "html.parser")
        require(runner["horse_name"] in soup.get_text(), "raw_audit_profile_name")
        values = {}
        for label in soup.find_all("dt"):
            key = label.get_text("",strip=True)
            if key in ("生産牧場", "父", "調教師名", "生年月日", "性別"):
                value = label.find_next_sibling("dd")
                if value:
                    values[key] = value.get_text(" ",strip=True)
        require(runner["horse_id"][:4] in values.get("生年月日", ""), "raw_audit_profile_birthyear")
        region = re.search(r"\((栗東|美浦)\)",norm(values.get("調教師名")))
        output.append({"horse_id":runner["horse_id"],"horse_name":runner["horse_name"],"breeder":values.get("生産牧場"),"sire":values.get("父"),
            "birth_date_raw":values.get("生年月日"),"current_trainer":values.get("調教師名"),"current_region":region[1] if region else None,
            "source_file":str(path.resolve()),"sha256":hashlib.sha256(raw).hexdigest(),"historical_affiliation_verified":False})
    return output


def summarize(rows, key, venue, first, last):
    """範囲と開催場を先に限定し、三群の四区分と全明細を保存する。"""
    scoped = [r for r in rows if first <= int(r["race_date"][:4]) <= last and (venue == "all" or r["venue_code"] == "08")]
    groups = {name: [r for r in scoped if r["conditions"][key] is value] for name, value in (("true", True), ("false", False), ("unknown", None))}
    return {"period": [first, last], "venue": venue, "total": counts(scoped), "groups": {k: counts(v) for k, v in groups.items()},
        "members": {k: [{f: r.get(f) for f in ("race_key", "race_date", "horse_id", "horse_no", "horse_name", "finish_rank")} for r in v] for k, v in groups.items()},
        "annual": {str(y): {k: counts([r for r in v if r["race_date"][:4] == str(y)]) for k, v in groups.items()} for y in sorted({int(r["race_date"][:4]) for r in scoped})}}


def captured(rows, truth, n):
    """同順位の確率値が等しい場合は枠を公平配分して好走捕捉を数える。"""
    total, start = 0., 0
    while start < len(rows):
        end = start+1
        while end < len(rows) and rows[end]["priority"] == rows[start]["priority"] and abs(rows[end]["probability_top3"]-rows[start]["probability_top3"]) < 1e-12:
            end += 1
        slots = max(0, min(n, end)-start)
        total += slots*sum(truth[r["horse_id"]] for r in rows[start:end])/(end-start)
        start = end
    return total


def priority_compare(examples, baseline):
    """原文の正条件は優先・負条件は後回しにして、順位用途を全件比較する。"""
    output = []
    for target in examples:
        if target["race_date"][:4] < "2008":
            continue
        base = next(p for p in baseline if p["race_key"] == target["race_key"] and p["pattern"] == "N+C+W")
        values = {r["horse_id"]: r for r in target["rows"]}
        truth = {r["horse_id"]: r["finish_rank"] in (1, 2, 3) for r in target["rows"]}
        for key, label, role, scope in [("baseline", "旧基準", "baseline", "all"), *RULES]:
            if scope == "kyoto" and target["venue_code"] != "08":
                continue
            ordered = []
            for row in base["runners"]:
                flag = values[row["horse_id"]]["conditions"].get(key)
                priority = 1 if flag is True and role == "positive" else -1 if flag is True and role == "negative" else 0
                ordered.append({**row, "priority": priority})
            ordered.sort(key=lambda r: (-r["priority"], -r["probability_top3"], int(r["horse_no"])))
            output.append({"rule_id": key, "race_key": target["race_key"], "race_date": target["race_date"], "top3_captured": captured(ordered, truth, 3),
                "top6_captured": captured(ordered, truth, 6), "top3": [r["horse_no"] for r in ordered[:3]], "top6": [r["horse_no"] for r in ordered[:6]]})
    result = []
    for key, label, role, scope in RULES:
        for first, last in ((2008, 2015), (2016, 2025), (2021, 2025)):
          for venue in ("all", "kyoto"):
            selected = [r for r in output if r["rule_id"] == key and first <= int(r["race_date"][:4]) <= last]
            if venue == "kyoto":
                selected = [r for r in selected if r["race_key"][8:10] == "08"]
            days = {r["race_key"] for r in selected}
            control = [r for r in output if r["rule_id"] == "baseline" and r["race_key"] in days]
            result.append({"rule_id": key, "label": label, "period": [first, last], "venue": venue, "races": len(selected),
                "candidate_top3": sum(r["top3_captured"] for r in selected), "baseline_top3": sum(r["top3_captured"] for r in control),
                "candidate_top6": sum(r["top6_captured"] for r in selected), "baseline_top6": sum(r["top6_captured"] for r in control),
                "status": "posthoc_priority_diagnostic_not_adoption_or_profit_validation"})
    return {"annual": output, "summaries": result}


def report(catalogue_rows, records, comparison, current, source_inventory):
    """全資料の確認範囲と使える候補/未検証を区別した日本語報告を作る。"""
    lines = ["# raw全4資料の条件監査", "", "資料は全件確認。原動画そのものの検証ではなく利用者提供要約の検証。過去成績の期間が不明な資料は2016〜2025を暫定比較として表示。", "",
        f"{len(catalogue_rows)}主張を台帳化、機械集計{len(records)}条件（重複を除く）。定義不足・不足データ・個別意見も台帳に全件保存。", "",
        "## 入力と境界", "", *[f"- {r['file']}：{r['bytes']} bytes／SHA {r['sha256']}" for r in source_inventory], "",
        "- 歴年前走/実績は保存国内履歴。海外未接続を非該当にしない。現在値が取れても過去年を充足したとしない。", "- 1-2-3-着外を表示。取消除外は実出走へ含めない。原文の数字と一致しない場合、期間や省略条件の差があり得るため誤りと断定しない。", "",
        "## 全条件の直近10年成績", "", table(["条件", "該当成績", "非該当成績", "不明成績", "該当頭数"], [[r["label"],r["recent"]["groups"]["true"]["record"],r["recent"]["groups"]["false"]["record"],r["recent"]["groups"]["unknown"]["record"],r["recent"]["groups"]["true"]["runners"]] for r in records]), "",
        "## 条件を優先/割引に使ったときの上位3捕捉", "", "正条件は該当馬を先、負条件は該当馬を後へ並べ、その中では旧基準順。条件が未知なら追加の不利益なし。点数への加算とは異なる用途。過去結果を見て方式を変更せず全件を表示。確率の新規推定・収益計算は行わない。", "",
        table(["条件", "2016〜25対象開催", "旧基準の好走捕捉", "条件優先/割引後", "旧上位6", "条件後上位6"], [[r["label"],r["races"],f"{r['baseline_top3']:g}",f"{r['candidate_top3']:g}",f"{r['baseline_top6']:g}",f"{r['candidate_top6']:g}"] for r in comparison["summaries"] if r["period"] == [2016,2025] and r["venue"] == "all"]), "",
        "## 京都開催だけの条件成績と用途比較", "", "資料3の成績は京都開催で複数再現。京都限定が元の意図だった可能性があり、原動画の省略条件は未確認。", "",
        table(["条件", "京都該当成績", "京都非該当成績", "不明", "旧→条件後の上位3捕捉"], [[r["label"],r["kyoto_recent"]["groups"]["true"]["record"],r["kyoto_recent"]["groups"]["false"]["record"],r["kyoto_recent"]["groups"]["unknown"]["record"],
             next(f"{c['baseline_top3']:g}→{c['candidate_top3']:g}" for c in comparison["summaries"] if c["rule_id"] == r["id"] and c["period"] == [2016,2025] and c["venue"] == "kyoto")] for r in records]), "",
        "## 全主張の対応台帳", "", table(["ID", "資料", "主張/視点", "状態", "対応規則/不足"], [[r["id"],r["file"],r["claim"],r["status"],r["rule_id"] or r["reason"]] for r in catalogue_rows]), "",
        "## 今年の候補条件該当（予想の変更ではない）", "", table(["馬番・馬名", "外枠19.9倍以下", "指定GI勝ち人気＋牡セン年齢", "高齢富士非好走の割引仮説", "前走国内6着以下"], [[f"{int(r['horse_no'])} {r['horse_name']}",*["○" if r["conditions"][k] is True else "×/収録内未確認" if r["conditions"][k] is False else "不明" for k in ("outer_price","specified_g1_win5_male6","age6_no_fuji2","previous_domestic6")]] for r in current]), "",
        "全条件の長期/場別/年度別/該当馬と反例はrecords.json、判定に使った実過去走はexamples.json/current.json。社台系救済は対象6頭の一次資料補完と暫定4牧場定義による再集計。全年度生産者網羅・持続力・馬場恩恵の補正は未完了。旧予想は更新していません。", ""]
    return "\n".join(lines)


def main():
    """全資料と旧版のSHAを固定し、用途別診断を新規出力先へ保存する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "raw_audit_output_exists")
    args.output.mkdir(parents=True)
    try:
        raw = Path("D:/develop/jra-scr/docs/raw")
        files = sorted(p for p in raw.iterdir() if p.is_file())
        require({p.name for p in files} == {"MC条件1.txt", "MC条件2.txt", "MC条件3.txt", "MC条件ゆっくり.txt"}, "raw_audit_new_or_missing_material")
        (args.output/"sources").mkdir()
        inventory = []
        for p in files:
            content = p.read_bytes()
            content.decode("utf-8-sig")
            (args.output/"sources"/p.name).write_bytes(content)
            inventory.append({"file": p.name, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
        datafile = ROOT/"artifacts/jra_research/graded_specific_20261120_coverage/mile-normalized.json"
        data = read(datafile)
        factsdir = ROOT/"artifacts/jra_research/mile_official_facts_20261122_v1"
        fact_map = {f["record_id"]: f for f in read(factsdir/"facts.json")}
        breederfile = ROOT/"artifacts/jra_research/mile_raw_supplements_20261122/breeders.json"
        breeders = {r["horse_id"]:r for r in read(breederfile)}
        link_map = {(l["race_key"],l["horse_id"]):l["record_id"] for l in read(factsdir/"links.json")}
        oldsets = read(ROOT/"artifacts/jra_research/mile_extension_v1_20261121/sets.json")["N"]
        truth = {(r["race_key"],r["horse_id"]):r for r in data["target_rows"] if r["status"] == "active"}
        examples, flat = [], []
        for t in oldsets:
            rows = []
            for r in t["rows"]:
                source = truth[(t["race_key"],r["horse_id"])]
                row = {**r,**rule_features(t,r,data["history"],[],link_map,fact_map,breeders=breeders),"race_key":t["race_key"],"race_date":t["race_date"],"venue_code":t["venue_code"],
                    "finish_rank":source["rank"],"nonfinish_confirmed":source["rank"] is None and source.get("abnormal_code") not in (None,"0")}
                rows.append(row)
                flat.append(row)
            examples.append({**t,"rows":rows})
        records = [{"id":k,"label":label,"role":role,"scope":scope,"recent":summarize(flat,k,scope,2016,2025),"long":summarize(flat,k,scope,2003,2025),
                    "earlier_reference":summarize(flat,k,scope,2003,2015),"kyoto_recent":summarize(flat,k,"kyoto",2016,2025),"kyoto_long":summarize(flat,k,"kyoto",2003,2025)} for k,label,role,scope in RULES]
        baselinefile = ROOT/"artifacts/jra_research/mile_extension_v1_20261121/predictions.json"
        comparison = priority_compare(examples,read(baselinefile))
        inputs = ROOT/"artifacts/jra_research/mile_integration_v1_20261122_inputs"
        card,parsed = read(inputs/"normalized-card.json"),read(inputs/"official-parsed-card.json")
        current_hist = ROOT/"artifacts/jra_research/graded_2026_inputs_20261120_audit/mile/normalized-jra-history.json"
        foreignfile = ROOT/"artifacts/jra_research/graded_2026_inputs_20261120_audit/non-jra-reference-records.json"
        observation = {int(r["horse_no"]):{"popularity":r.get("popularity"),"win_odds":r.get("odds")} for r in parsed["runners"]}
        profile_facts = current_profile_facts(card)
        current_breeders = {**breeders,**{r["horse_id"]:r for r in profile_facts}}
        current = [{**r,**rule_features(card,r,read(current_hist),read(foreignfile),link_map,fact_map,observation[int(r["horse_no"])],current_breeders)} for r in card["runners"]]
        entries = catalogue()
        require({c["file"] for c in entries} == {p.name for p in files}, "raw_audit_catalog_files")
        for name,value in (("inventory",inventory),("catalogue",entries),("examples",examples),("records",records),("priority-comparison",comparison),("current",current),("current-profile-facts",profile_facts)):
            save(args.output/(name+".json"),value)
        (args.output/"report.md").write_text(report(entries,records,comparison,current,inventory),encoding="utf-8")
        sources = [Path(__file__),datafile,factsdir/"facts.json",factsdir/"links.json",baselinefile,current_hist,foreignfile,breederfile,inputs/"normalized-card.json",inputs/"official-parsed-card.json",*files,*[Path(r["source_file"]) for r in profile_facts],
             *[breederfile.parent/r["source_file"] for r in breeders.values()]]
        save(args.output/"manifest.json",{"inputs":{str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},"outputs":{str(p.relative_to(args.output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.rglob('*') if p.is_file()}})
        print(json.dumps({"files":len(files),"claims":len(entries),"tested_rules":len(records),"historic_rows":len(flat),"current_rows":len(current),"priority_predictions":len(comparison["annual"])},ensure_ascii=False))
    except Exception as error:
        save(args.output/"failure.json",{"type":type(error).__name__,"reason":getattr(error,"reason",str(error))})
        raise


if __name__ == "__main__":
    main()
