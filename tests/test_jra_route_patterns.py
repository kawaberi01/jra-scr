"""概要: 経路・消去パターンの時点、順序、三値と集計を検証する。
作成日: 2026-11-22
入力: 人工的な過去走・カード・経路条件。
出力: pytest結果。
実行例: uv run pytest -q tests/test_jra_route_patterns.py
注意事項: 外部通信・DB変更なし。
"""

from jra_srb.jra_route_patterns import patterns,match,counts,summarize,evaluate,live


def row(day,name,rank=1,status="active"):
    """テスト用の同一馬の過去走を返す。"""
    return {"race_key":day.replace("-","")+"0511","race_date":day,"race_name":name,"horse_id":"1234567890","status":status,"rank":rank,"distance":1600}


def check(pid,history,age=5):
    """11月22日を対象として指定パターンを判定する。"""
    target={"race_date":"2026-11-22"}; runner={"horse_id":"1234567890","age":age}
    return match(target,runner,history,next(p for p in patterns() if p["id"]==pid))


def test_fixed_48_patterns():
    """候補が48件で重複しない。"""
    assert len(patterns())==len({p["id"] for p in patterns()})==48


def test_previous_and_same_year_differ():
    """同年に出走しても直前走でないケースを区別する。"""
    h=[row("2026-10-17","富士ステークス",2),row("2026-11-01","別レース",1)]
    assert check("previous-1-3",h)["matched"] is False
    assert check("same_year-1-3",h)["matched"] is True


def test_rank_unknown_not_failure():
    """順位欠測は出走事実と好走不明に分離する。"""
    h=[row("2026-10-17","富士ステークス",None)]
    assert check("previous-1-0",h)["matched"] is True
    assert check("previous-1-3",h)["matched"] is None


def test_no_history_unknown():
    """履歴なしを未出走と断定しない。"""
    assert check("same_year-1-0",[])["matched"] is None


def test_future_and_excluded_removed():
    """取消・当日・未来の結果は使わない。"""
    h=[row("2026-10-01","別レース",7),row("2026-10-17","富士ステークス",1,"excluded"),row("2026-11-22","富士ステークス",1),row("2027-10-17","富士ステークス",1)]
    assert check("same_year-1-0",h)["matched"] is False
    assert check("previous_result-1",h)["matched"] is False


def test_sequence_order_matters():
    """経路は前後順が一致した場合のみ採用する。"""
    h=[row("2026-06-07","安田記念",2),row("2026-10-17","富士ステークス",3)]
    assert check("sequence-1-3",h)["matched"] is True
    inverse=[row("2026-06-07","富士ステークス",3),row("2026-10-17","安田記念",2)]
    assert check("sequence-1-0",inverse)["matched"] is False


def test_previous_year_boundary():
    """前年と前々年の同名競走を区別する。"""
    assert check("previous_year-3",[row("2025-11-23","マイルチャンピオンシップ",2)])["matched"] is True
    assert check("previous_year-3",[row("2024-11-17","マイルチャンピオンシップ",2)])["matched"] is False


def test_age_without_history():
    """年齢条件は履歴不要で、年齢不明は欠測とする。"""
    assert check("age_max-4",[],4)["matched"] is True
    assert check("age_max-4",[],5)["matched"] is False
    assert check("age_max-4",[],None)["matched"] is None


def test_crowned_alias():
    """既存の冠名対応を再利用する。"""
    assert check("previous-2-3",[row("2026-10-12","MBS賞スワンステークス",3)])["matched"] is True


def test_counts_and_unknown_retention():
    """不明は残し、非該当の勝ち馬は例外として列挙する。"""
    rows=[{"race_key":"x","race_date":"2020-11-20","horse_no":str(i),"horse_name":str(i),"rank":i,"patterns":{"p":{"matched":v}}} for i,v in ((1,False),(2,True),(3,None))]
    s=summarize(rows,"p")
    assert s["total"]==counts(rows)
    assert s["matched"]["top3"]==1 and s["unknown"]["top3"]==1
    assert s["retained"]["runners"]==2 and s["retained_winner_rate"]==0
    assert len(s["excluded_winners"])==1


def test_foreign_actual_previous_not_domestic_substitute():
    """海外実前走を保持し、国内最終走を前走と誤認しない。"""
    card={"race_date":"2026-11-22","runners":[{"horse_id":"1234567890","status":"active"}]}
    f=[{"horse_id":"1234567890","jra_race_key":None,"race_date":"2026-11-01","race_name_raw":"海外GI","rank":1,"distance":1600}]
    x=live(card,[row("2026-10-17","富士ステークス",2)],f)[0]
    assert x["patterns"]["previous-1-3"]["matched"] is False
    assert x["patterns"]["same_year-1-3"]["matched"] is True


def test_selection_uses_development_only():
    """確認期で勝ち馬を落としても開発で選んだ条件を差し替えない。"""
    rows=[]
    for year in range(2008,2026):
        for rank in (1,2,3):
            rows.append({"race_key":str(year),"race_date":f"{year}-11-20","horse_no":str(rank),"horse_name":str(rank),"rank":rank,
                "patterns":{p["id"]:{"matched":p["id"]=="age_max-5" and year<=2020 and rank<=2} for p in patterns()}})
    result=evaluate(rows)
    assert result["selected_elimination_pattern"]["id"]=="age_max-5"
    assert result["selected_elimination_pattern"]["periods"]["confirmation"]["retained_winner_rate"]==0
    assert result["adopted"] is False
