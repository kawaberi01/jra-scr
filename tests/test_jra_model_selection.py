"""概要: JRA共通モデル選択の承認・完全性・表示保存・全日比較を検証する。
作成日: 2026-10-25
入力: 一時設定・人工確率・隔離Store代替。
出力: pytest結果。
実行例: uv run --extra ml --extra dev pytest -q tests/test_jra_model_selection.py
注意事項: 実購入・実SQL更新・外部通信・再学習なし。実モデル確認は別のCLI監査で行う。
"""

from copy import deepcopy
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from jra_srb import jra_model_selection as selection

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """既定と別モデルの承認状態を操作できる隔離設定を作る。"""
    data = selection.read_json(selection.DEFAULT_CONFIG)
    model = data["models"]["attribute-d0-v3"]
    folder = tmp_path / "artifact"
    folder.mkdir()
    artifact = folder / "final_model.joblib"
    artifact.write_bytes(b"verified-test-artifact")
    assessment = {"replace_H2_as_research_candidate": True, "production_adoption": False}
    (folder / "assessment.json").write_text(json.dumps(assessment), encoding="utf-8")
    manifest = {"model_sha256": selection.sha256(artifact), "selected": "D0",
                "assessment_sha256": selection.sha256(folder / "assessment.json"),
                "trained_through": model["trained_through"], "train_ids": ["202001050601", "202512280601"]}
    (folder / "model-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "independent-verification.json").write_text('{"status":"passed"}', encoding="utf-8")
    model.update(artifact="artifact/final_model.joblib", sha256=manifest["model_sha256"])
    path = tmp_path / "models.json"
    monkeypatch.setattr(selection, "ROOT", tmp_path)
    return data, path, folder


def choose(registry, requested=None):
    """変更した隔離台帳で選択を実行する。"""
    data, path, _ = registry
    path.write_text(json.dumps(data), encoding="utf-8")
    return selection.resolve_model(requested, path)


def test_default_and_explicit_priority(registry):
    """未指定は承認済み既定、明示指定は別モデルと別名を優先する。"""
    assert choose(registry)["id"] == "attribute-d0-v3"
    assert choose(registry, "D0")["selection_source"] == "explicit"
    assert choose(registry, "V89")["id"] == "v89"
    assert choose(registry, "v90")["id"] == "v90"


@pytest.mark.parametrize("state", ["experimental", "rejected", "pending"])
def test_unverified_or_rejected_never_selected(registry, state):
    """新番号モデルが増えても選択せず、既定を誤設定した場合は停止する。"""
    data, _, _ = registry
    entry = deepcopy(data["models"]["attribute-d0-v3"])
    entry.update(validation=state, aliases=["V999"])
    data["models"]["newest-model-v999"] = entry
    assert choose(registry)["id"] == "attribute-d0-v3"
    data["default_model"] = "newest-model-v999"
    with pytest.raises(ValueError, match="未検証"):
        choose(registry)
    with pytest.raises(ValueError):
        choose(registry, "V999")


@pytest.mark.parametrize("failure", ["disabled", "missing", "hash", "approval", "verification", "purchase"])
def test_unavailable_stops_without_fallback(registry, failure):
    """利用不能・改竄・未承認を別モデルへの代替で隠さない。"""
    data, _, folder = registry
    model = data["models"]["attribute-d0-v3"]
    if failure == "disabled":
        model["availability"] = "disabled"
    elif failure == "missing":
        (folder / "final_model.joblib").unlink()
    elif failure == "hash":
        (folder / "final_model.joblib").write_bytes(b"different")
    elif failure == "approval":
        model["default_eligible"] = False
    elif failure == "verification":
        (folder / "independent-verification.json").write_text('{"status":"failed"}', encoding="utf-8")
    else:
        model["purchase_allowed"] = True
    with pytest.raises((ValueError, OSError)):
        choose(registry)
    assert choose(registry, "V89")["id"] == "v89"


def test_unknown_explicit_is_not_default(registry):
    """誤記の明示指定を既定へ置換しない。"""
    with pytest.raises(ValueError, match="未登録"):
        choose(registry, "missing-model")


@pytest.fixture
def j23_registry(registry):
    """固定J23のファイル照合だけを行う隔離設定を用意する。"""
    data, path, folder = registry
    entry = data["models"]["j23-fixed-2026-09"]
    artifact = folder / "J23.joblib"
    artifact.write_bytes(b"test-frozen-J23")
    cell = folder / "J23.json"
    cell.write_text(json.dumps({"case": "J23", "status": "evaluated", "model_file": artifact.name,
        "model_sha256": selection.sha256(artifact), "trained_through": "2026-08-30", "reload_checks": 3}), encoding="utf-8")
    entry.update(artifact="artifact/J23.joblib", model_cell="artifact/J23.json",
                 sha256=selection.sha256(artifact), model_cell_sha256=selection.sha256(cell))
    return registry


def test_j23_explicit_only_keeps_default(j23_registry):
    """J23指定だけを優先し、設定誤変更でも明示専用モデルを既定にしない。"""
    assert choose(j23_registry)["id"] == "attribute-d0-v3"
    selected = choose(j23_registry, "J23")
    assert selected["id"] == "j23-fixed-2026-09" and selected["purchase_allowed"] is False
    data, _, _ = j23_registry
    data["default_model"] = selected["id"]
    data["models"][selected["id"]]["default_eligible"] = True
    with pytest.raises(ValueError, match="明示指定専用"):
        choose(j23_registry)


@pytest.mark.parametrize("fault", ["hash", "cell", "purchase", "disabled"])
def test_j23_invalid_state_is_not_replaced(j23_registry, fault):
    """J23の不備・購入承認の誤変更を拒否し、D0へ代替しない。"""
    data, _, folder = j23_registry
    entry = data["models"]["j23-fixed-2026-09"]
    if fault == "hash":
        (folder / "J23.joblib").write_bytes(b"changed")
    elif fault == "cell":
        (folder / "J23.json").write_text("{}", encoding="utf-8")
    elif fault == "purchase":
        entry["purchase_allowed"] = True
    else:
        entry["availability"] = "disabled"
    with pytest.raises((ValueError, KeyError)):
        choose(j23_registry, "J23")


@pytest.fixture
def workflow(monkeypatch):
    """案件の共通入口をimportし、副作用のない関数をテストする。"""
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    return importlib.import_module("jra_selected_model")


@pytest.fixture
def sample(registry, workflow):
    """着順とは異なる周辺順位とオッズを持つ事前入力を作る。"""
    model = choose(registry)
    now = datetime.now(timezone.utc)
    day = "2099-10-25"
    numbers = ["08", "02", "01", "03", "04", "05"]
    card = {"race_id": "209910250811", "race_name": "検証", "start_time": "15時40分",
            "runners": [{"horse_no": n, "horse_name": n, "status": "active"} for n in numbers],
            "fetched_at": now.isoformat(), "source": "https://www.jra.go.jp/", "data_status": {}}
    odds = {"fetched_at": now.isoformat(), "odds": {"win": [
        {"combination": [n], "odds": str(price)} for n, price in zip(numbers, [2, 4, 12, 14, 20, 30])]}}
    forecast = {"race_id": card["race_id"], "race_date": day,
                "horse_ranking": [{"horse_no": n, "top2_probability": .7-i*.1} for i, n in enumerate(numbers)],
                "pair_ranking": [{"horses": ["02", "08"], "probability": .24}], "horse_names": {}}
    return model, forecast, {"card": card, "odds": odds}, now


def test_model_semantics_and_budget_do_not_become_v_or_win(workflow, sample):
    """高予算でも研究順位と確率対象を保ち、別モデルや未実装券種へ変えない。"""
    model, forecast, snapshot, now = sample
    payload = workflow.build_payload(model, forecast, snapshot, now, budget=100000)
    p = payload["prediction_json"]
    assert [r["horse_no"] for r in p["predicted_ranking"]] == [r["horse_no"] for r in forecast["horse_ranking"]]
    assert p["marks"]["08"] == "◎" and p["axis_horse_numbers"] == ["08"]
    assert p["predicted_top3"] == p["head_horse_numbers"] == []
    assert payload["budget"] == p["purchase_yen"] == 0 and payload["prediction_tickets"] == []
    assert p["selected_model"]["purchase_allowed"] is False
    assert p["probability_capabilities"] == ["quinella", "top2_marginal"]
    assert p["dansou_reference"]["main_tickets_changed"] is False
    assert workflow.scout_metric(model, payload) == .24
    assert "2着内周辺確率" in workflow.render(payload)


def test_old_input_timestamp_not_relabelled(workflow, sample):
    """保存時刻が新しくても、早朝の実観測と古さを保持する。"""
    from datetime import timedelta
    model, forecast, snapshot, now = sample
    early = (now-timedelta(hours=4)).isoformat()
    snapshot["odds"]["fetched_at"] = early
    payload = workflow.build_payload(model, forecast, snapshot, now)
    state = payload["prediction_json"]["input_state"]
    assert state["odds"]["observed_at"] == early
    assert state["odds"]["freshness"] == "older_snapshot_recheck_required"
    assert state["near_post_latest_verified"] is False
    assert early in workflow.render(payload)


def test_missing_or_changed_roster_and_stale_input_rejected(workflow, sample):
    """取消や古すぎる入力を無視して既存順位を保存しない。"""
    from datetime import timedelta
    model, forecast, snapshot, now = sample
    snapshot["card"]["runners"][0]["status"] = "withdrawn"
    with pytest.raises(ValueError, match="出走馬集合"):
        workflow.build_payload(model, forecast, snapshot, now)
    snapshot["odds"]["fetched_at"] = (now-timedelta(days=2)).isoformat()
    with pytest.raises(ValueError, match="24時間"):
        workflow.build_payload(model, forecast, snapshot, now)


def test_store_roundtrip_preserves_presentation_and_refuses_overwrite(workflow, sample, monkeypatch):
    """表示全文と構造化値を読み戻し、同じIDの上書きと表示だけの変更を拒否する。"""
    import jra_srb.storage as storage
    import jra_srb.storage_config as config
    model, forecast, snapshot, now = sample
    payload = workflow.build_payload(model, forecast, snapshot, now)
    payload["prediction_json"]["presentation_markdown"] = workflow.render(payload)
    records = {}

    class Store:
        """新IDの保存と完全読戻しだけを提供する隔離Store。"""

        def get_prediction_record(self, key):
            """保存済みの値を返し、未登録IDはLookupErrorとする。"""
            if key not in records:
                raise LookupError(key)
            return records[key]

        def upsert_prediction_record(self, value):
            """深いコピーを使い、保存後の変更が読戻しへ漏れないようにする。"""
            copy = json.loads(json.dumps(value))
            records[value["prediction_id"]] = SimpleNamespace(
                prediction=copy["prediction_json"], pre_race_snapshot=copy["pre_race_snapshot"],
                race_id=copy["race_id"], budget=copy["budget"], prediction_tickets=copy["prediction_tickets"])

    monkeypatch.setattr(storage, "build_analysis_store", lambda _: Store())
    monkeypatch.setattr(config, "storage_backend", lambda: "sqlserver")
    assert workflow.save_prediction(payload)["sql_readback_verified"]
    with pytest.raises(ValueError, match="上書き"):
        workflow.save_prediction(payload)
    payload["prediction_json"]["marks"]["08"] = "○"
    with pytest.raises(ValueError, match="表示本文"):
        workflow.save_prediction(payload)


def test_scout_keeps_missing_entries_and_model(workflow, sample, tmp_path, monkeypatch):
    """全日比較で不足レースを削除せず、共通モデルと指標だけを使う。"""
    model, forecast, snapshot, now = sample
    payload = workflow.build_payload(model, forecast, snapshot, now)
    day = forecast["race_date"]
    index = tmp_path / "index.json"
    index.write_text(json.dumps({"date": day, "races": [
        {"race_id": "209910250811", "course": "kyoto", "race_no": 11, "start_time": "15時40分", "snapshot_dir": "prepared"},
        {"race_id": "209910250812", "course": "kyoto", "race_no": 12, "start_time": "16時20分"}]}), encoding="utf-8")
    monkeypatch.setattr(workflow, "predict", lambda *args, **kwargs: payload)
    args = SimpleNamespace(date=day, output=tmp_path / "day", snapshot_index=index, max_fetches=0)
    report = workflow.scout(args, model, None)
    assert report["status"] == "partial" and len(report["entries"]) == 2
    assert report["selected_model"]["id"] == model["id"]
    assert report["ranked"][0]["metric"] == .24
    assert report["entries"][1]["status"] == "unavailable"
    assert report["all_day_highest_confidence_proven"] is False


def test_unsupported_scout_metric_is_not_legacy_fallback(workflow):
    """比較未対応モデルを従来の勝率差へ戻さない。"""
    with pytest.raises(ValueError, match="未実装"):
        workflow.scout_metric({"id": "v89"}, {})


def test_v_model_mismatch_does_not_score_another_v(workflow, tmp_path):
    """対象場で返されたV版が指定と異なる時は停止する。"""
    (tmp_path / "model-comparison.json").write_text(json.dumps({"v_theory": {
        "theory_version": "v90", "status": "available", "ranking": [{"horse_no": "01"}]}}), encoding="utf-8")
    model = {"id": "v89", "adapter": "v_theory", "courses": ["kyoto"]}
    with pytest.raises(ValueError, match="指定Vモデルが利用不可"):
        workflow.predict(model, tmp_path, tmp_path / "result", course="kyoto")


def test_live_acquisition_requests_fresh_card(workflow, tmp_path):
    """live取得では再取得カードと束の馬集合の不一致を検知する。"""
    paths = []

    def handle(request):
        """時刻付きの人工公式束をローカルHTTP代替で返す。"""
        paths.append(str(request.url))
        if request.url.path.endswith("/card"):
            return httpx.Response(200, json={"runners": [{"horse_no": "01"}]})
        if request.url.path.endswith("/prediction-bundle"):
            return httpx.Response(200, json={"card": {"runners": [{"horse_no": "02"}]}})
        return httpx.Response(200, json={"meeting_no": 1, "meeting_day": 1,
            "races": [{"race_no": 11, "start_time": "15時40分"}]})

    with httpx.Client(base_url="http://local.test", transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError, match="出走馬情報が変化"):
            workflow.acquire_snapshot(client, "2099-10-25", "kyoto", 11, {"adapter": "v_theory"}, tmp_path / "snapshot")
    assert any("/card?refresh=true" in path for path in paths)


def test_v_explicit_ranking_keeps_raw_state(workflow, sample, tmp_path):
    """V系指定時は既存順位と元のshadow状態を保持し、確率を生成しない。"""
    _, forecast, snapshot, _ = sample
    model = {"id": "v89", "name": "V89", "version": "existing", "selection_source": "explicit",
             "adapter": "v_theory", "courses": ["kyoto"], "probabilities": [],
             "ranking_semantics": "v_theory_score_not_probability", "availability": "enabled",
             "validation": "legacy_explicit", "research_allowed": True, "purchase_allowed": False}
    ranks = [{"horse_no": r["horse_no"], "score": i} for i, r in enumerate(reversed(forecast["horse_ranking"]))]
    for file, value in [("official-card.json", snapshot["card"]), ("official-odds.json", snapshot["odds"]),
                         ("model-comparison.json", {"v_theory": {"status": "available", "theory_version": "v89",
                             "betting_status": "shadow_only", "ranking": ranks}})]:
        (tmp_path / file).write_text(json.dumps(value), encoding="utf-8")
    payload = workflow.predict(model, tmp_path, tmp_path / "v89-result", course="kyoto")
    assert payload["prediction_json"]["selected_model"]["id"] == "v89"
    assert payload["prediction_json"]["axis_horse_numbers"] == [ranks[0]["horse_no"]]
    assert payload["prediction_json"]["forecast"]["raw_v_status"]["betting_status"] == "shadow_only"
    assert payload["prediction_json"]["probability_capabilities"] == []
    assert payload["budget"] == 0


def test_card_api_forwards_refresh_to_existing_service(monkeypatch):
    """カードAPIのrefresh指定がキャッシュ再利用に固定されないことを確認する。"""
    from fastapi.testclient import TestClient
    from jra_srb.app import app, get_service
    observed = []

    class Service:
        """呼び出された再取得フラグを記録するサービス代替。"""

        async def get_race_card_by_number(self, day, course, race_no, refresh=False):
            """実通信せず、呼出し条件を記録する。"""
            observed.append(refresh)
            return {"refresh": refresh}

    monkeypatch.setitem(app.dependency_overrides, get_service, lambda: Service())
    with TestClient(app) as client:
        assert client.get("/meetings/2026-10-25/kyoto/races/11/card?refresh=true").status_code == 200
        assert client.get("/meetings/2026-10-25/kyoto/races/11/card").status_code == 200
    assert observed == [True, False]


@pytest.mark.parametrize("adapter", ["attribute_chimera", "j23_frozen"])
def test_attribute_live_uses_required_official_inputs_only(workflow, tmp_path, monkeypatch, adapter):
    """研究モデルに不要な外部分析の取得に依存せず、履歴準備後のカードと価格を再確認する。"""
    import prepare_jra_condition_input as preparation
    from jra_srb.jra_model_selection import sha256
    paths = []
    card = {"race_id": "209910250811", "start_time": "15時40分", "surface": "芝", "distance": "3000",
            "fetched_at": datetime.now(timezone.utc).isoformat(), "runners": [{"horse_no": "01", "status": "active"}]}

    def prepare(args):
        """SQL接続せず、同定済み特徴の最小ファイルを作成する。"""
        args.output.mkdir()
        (args.output / "input.json").write_text('{"race_id":"209910250811"}', encoding="utf-8")
        (args.output / "j23_public_features.json").write_text('{"race_id":"209910250811","x":[]}', encoding="utf-8")
        (args.output / "quality.json").write_text(json.dumps({"status": "passed", "card_sha256": sha256(args.card)}), encoding="utf-8")

    def handle(request):
        """必要な公式APIのみを提供し、余計なAPIをテスト失敗にする。"""
        paths.append(request.url.path)
        if request.url.path.endswith("/card"):
            return httpx.Response(200, json=card)
        if request.url.path.endswith("/odds-summary"):
            assert request.url.params["bet_types"] == "win,quinella"
            return httpx.Response(200, json={"race_id": card["race_id"], "fetched_at": card["fetched_at"], "odds": {}})
        assert request.url.path == "/meetings/2099-10-25/kyoto"
        return httpx.Response(200, json={"meeting_no": 1, "meeting_day": 1,
            "races": [{"race_no": 11, "start_time": "15時40分"}]})

    monkeypatch.setattr(preparation, "prepare", prepare)
    with httpx.Client(base_url="http://local.test", transport=httpx.MockTransport(handle)) as client:
        source = workflow.acquire_snapshot(client, "2099-10-25", "kyoto", 11,
            {"adapter": adapter, "history_checkpoint_run": "fixed-history"}, tmp_path / "live")
    assert paths.count("/meetings/2099-10-25/kyoto/races/11/card") == 2
    assert not any("prediction-bundle" in path for path in paths)
    assert (source / "input/quality.json").exists()
    assert json.loads((source / "input/quality.json").read_text(encoding="utf-8"))["post_preparation_roster_equal"]
    assert (source / "input/j23_public_features.json").exists()


def test_j23_prediction_never_invokes_d0(workflow, sample, tmp_path, monkeypatch):
    """J23ルートではD0推論を呼ばず、表示・保存対象もJ23の出力を使う。"""
    import score_jra_attribute_chimera as attribute
    model, forecast, snapshot, _ = sample
    selected = {**model, "id": "j23-fixed-2026-09", "name": "J23", "adapter": "j23_frozen", "selection_source": "explicit"}
    calls = []

    def j23_score(model, source):
        """J23専用呼出しを記録して、D0と異なる順位を返す。"""
        calls.append(model["id"])
        result = deepcopy(forecast)
        result["horse_ranking"] = list(reversed(result["horse_ranking"]))
        return result, snapshot

    def reject_d0(*args, **kwargs):
        """誤ってD0へ切替した場合はテストを失敗させる。"""
        raise AssertionError("J23指定でD0を実行")

    monkeypatch.setattr(workflow, "score_j23_snapshot", j23_score)
    monkeypatch.setattr(attribute, "score", reject_d0)
    payload = workflow.predict(selected, tmp_path, tmp_path / "j23-result")
    assert calls == ["j23-fixed-2026-09"]
    assert payload["prediction_json"]["axis_horse_numbers"] == [forecast["horse_ranking"][-1]["horse_no"]]
    assert payload["prediction_json"]["selected_model"]["selection_source"] == "explicit"
    assert payload["budget"] == 0 and payload["prediction_tickets"] == []


def test_j23_adapter_probabilities_and_explicit_cancellation(workflow, tmp_path, monkeypatch):
    """J23実推論式・取消除外・周辺確率を確認し、明示根拠のない除外を拒否する。"""
    from itertools import combinations
    import numpy as np
    from jra_srb import jra_research_j23_live as legacy
    numbers = [f"{i:02d}" for i in range(1, 9)]
    now = datetime.now(timezone.utc).isoformat()
    card = {"race_id": "209910250510", "start_time": "14時45分", "fetched_at": now,
        "source": "https://www.jra.go.jp/JRADB/accessD.html", "data_status": {"runner_set": "complete", "source_kind": "pre_race_card"},
        "runners": [{"horse_no": h, "horse_name": h, "status": "active"} for h in numbers] +
                   [{"horse_no": "09", "horse_name": "取消", "status": "withdrawn", "status_source": "explicit"}]}
    all_numbers = numbers + ["09"]
    odds = {"race_id": card["race_id"], "fetched_at": now, "source": card["source"], "odds": {
        "win": [{"combination": [h], "odds": str(2+i)} for i, h in enumerate(all_numbers)],
        "quinella": [{"combination": list(pair), "odds": str(5+i)} for i, pair in enumerate(combinations(all_numbers, 2))]}}
    (tmp_path / "input").mkdir()
    for name, value in [("official-card.json", card), ("official-odds.json", odds),
                        ("input/input.json", {"race_id": card["race_id"], "race_date": "2099-10-25", "horses": numbers, "surface": 0, "distance": 1800}),
                        ("input/j23_public_features.json", {"race_id": card["race_id"], "race_date": "2099-10-25", "horses": numbers, "x": np.zeros((8, 12)).tolist()})]:
        (tmp_path / name).write_text(json.dumps(value), encoding="utf-8")
    quality = {"status": "passed", "card_sha256": selection.sha256(tmp_path / "official-card.json")}
    (tmp_path / "input/quality.json").write_text(json.dumps(quality), encoding="utf-8")
    model = {"sha256": "fixed-sha", "trained_through": "2026-08-30"}
    fitted = {"case": "J23", "coef": np.zeros(28), "scale": np.ones(28)}
    monkeypatch.setattr(legacy, "load_frozen", lambda day: (fitted, {}, {"model_sha256": "fixed-sha", "trained_through": "2026-08-30"}))
    forecast, snapshot = workflow.score_j23_snapshot(model, tmp_path)
    assert forecast["case"] == "J23" and forecast["result_ignored"]
    assert len(forecast["horse_ranking"]) == 8 and len(forecast["pair_ranking"]) == 28
    assert all("09" not in row["horses"] for row in forecast["pair_ranking"])
    assert sum(row["probability"] for row in forecast["pair_ranking"]) == pytest.approx(1.)
    assert sum(row["top2_probability"] for row in forecast["horse_ranking"]) == pytest.approx(2.)
    prices = {tuple(row["combination"]): float(row["odds"]) for row in snapshot["odds"]["odds"]["quinella"]}
    denominator = sum(1/value for value in prices.values())
    for row in forecast["pair_ranking"]:
        assert row["probability"] == pytest.approx((1/prices[tuple(row["horses"])])/denominator)
    assert snapshot["source_odds"] == odds and len(odds["odds"]["quinella"]) == 36
    card["runners"][-1]["status_source"] = "unknown"
    (tmp_path / "official-card.json").write_text(json.dumps(card), encoding="utf-8")
    quality["card_sha256"] = selection.sha256(tmp_path / "official-card.json")
    (tmp_path / "input/quality.json").write_text(json.dumps(quality), encoding="utf-8")
    with pytest.raises(ValueError, match="取消根拠"):
        workflow.score_j23_snapshot(model, tmp_path)


def test_result_comparison_uses_only_available_probability_targets(workflow, sample):
    """結果比較で馬連と2着内事実を扱い、単勝勝率や的中利益を作らない。"""
    from jra_srb.analysis_store import _evaluate_selected_model_outputs
    model, forecast, snapshot, now = sample
    payload = workflow.build_payload(model, forecast, snapshot, now)
    p = payload["prediction_json"]
    result = [{"horse_no": "8", "rank": 1}, {"horse_no": "2", "rank": 2}, {"horse_no": "1", "rank": 3}]
    evaluation = _evaluate_selected_model_outputs(p, result)
    assert evaluation["quinella_top_pair_hit"] is True
    assert evaluation["actual_pair_probability"] == .24
    assert evaluation["top2_marginal_outcomes"][0]["finished_top2"] is True
    assert evaluation["purchase_status"] == "未購入"
    assert "win_probability" not in evaluation and "winner_hit" not in evaluation
    result[1]["rank"] = 1
    assert _evaluate_selected_model_outputs(p, result)["status"] == "unavailable"


def test_saved_evaluation_marks_finish_metrics_not_applicable(workflow, sample, tmp_path):
    """保存から評価読戻しまで、着順非対応を不的中にせず未購入として保持する。"""
    from jra_srb.analysis_store import AnalysisSQLiteStore
    from jra_srb.models import RaceResult, ResultEntry, PayoutEntry
    model, forecast, snapshot, now = sample
    payload = workflow.build_payload(model, forecast, snapshot, now)
    store = AnalysisSQLiteStore(tmp_path / "isolated-contract.sqlite")
    store.upsert_prediction_record(payload)
    store.write_result(RaceResult(race_id=payload["race_id"], race_name="隔離評価",
        results=[ResultEntry(rank="1", horse_no="8", horse_name="8"),
                 ResultEntry(rank="2", horse_no="2", horse_name="2"),
                 ResultEntry(rank="3", horse_no="1", horse_name="1")],
        payouts=[PayoutEntry(bet_type="quinella", combination="2-8", payout="1000")],
        fetched_at=now, source="isolated-fixture"))
    store.evaluate_prediction_record({"prediction_id": payload["prediction_id"], "evaluation_id": "isolated-eval"})
    saved = store.get_evaluation_record("isolated-eval")
    summary = saved.evaluation["summary"]
    assert summary["winner_hit"] is None and summary["top3_box_hit"] is None
    assert summary["finish_order_metrics_applicable"] is False
    assert summary["model_output_evaluation"]["quinella_top_pair_hit"] is True
    assert saved.total_bet == saved.total_payout == 0 and not saved.ticket_results


@pytest.fixture
def priced_sample(sample):
    """馬連3点の実オッズを追加し、研究予想の仮想配分を検証可能にする。"""
    model, forecast, snapshot, now = deepcopy(sample)
    forecast["pair_ranking"] = [
        {"horses": ["02", "08"], "probability": .24},
        {"horses": ["01", "08"], "probability": .15},
        {"horses": ["03", "08"], "probability": .1}]
    snapshot["odds"]["odds"]["quinella"] = [
        {"combination": row["horses"][::-1], "odds": str(price)}
        for row, price in zip(forecast["pair_ranking"], [4.5, 8, 10])]
    return model, forecast, snapshot, now


def test_research_predicts_without_purchase_approval(workflow, priced_sample):
    """未承認でも具体的な仮想買い目を作り、実投資・着順予測から分離する。"""
    model, forecast, snapshot, now = priced_sample
    payload = workflow.build_payload(model, forecast, snapshot, now)
    prediction = payload["prediction_json"]
    plan = prediction["research_plan"]
    assert plan["status"] == "available" and plan["virtual_only"]
    assert [row["selection"] for row in plan["tickets"]] == [["02", "08"], ["01", "08"], ["03", "08"]]
    assert [row["amount"] for row in plan["tickets"]] == [500, 300, 200]
    assert plan["virtual_budget_yen"] == plan["total_stake_yen"] == 1000
    assert plan["observed_at"] == snapshot["odds"]["fetched_at"]
    assert model["purchase_allowed"] is False
    assert payload["budget"] == prediction["purchase_yen"] == 0 and not payload["prediction_tickets"]
    assert prediction["predicted_top3"] == []
    assert "02-08" in workflow.render(payload)
    plan["tickets"][0]["amount"] = 600
    with pytest.raises(ValueError, match="研究プラン"):
        workflow.render(payload)


def test_virtual_budget_rounding_and_single_evaluation_plan(workflow, priced_sample):
    """指定予算を100円単位で余りなく配分し、他の予算例は選択プランへ混ぜない。"""
    model, forecast, snapshot, now = priced_sample
    for budget in [100, 200, 700, 1300, 2300]:
        plan = workflow.build_payload(model, forecast, snapshot, now, budget)["prediction_json"]["research_plan"]
        assert sum(row["amount"] for row in plan["tickets"]) == budget
        assert all(row["amount"] >= 100 and row["amount"] % 100 == 0 for row in plan["tickets"])
        assert {row["budget_yen"] for row in plan["budget_plans"]} == {1000, 2000, 3000, budget}
    for budget in [50, 1050, -100]:
        with pytest.raises(ValueError, match="仮想予算"):
            workflow.build_payload(model, forecast, snapshot, now, budget)


def test_missing_price_keeps_prediction_without_inventing_stakes(workflow, priced_sample):
    """上位候補の価格不足では別候補に差し替えず、予想を残して仮想配分だけ保留する。"""
    model, forecast, snapshot, now = priced_sample
    snapshot["odds"]["odds"]["quinella"].pop()
    payload = workflow.build_payload(model, forecast, snapshot, now)
    plan = payload["prediction_json"]["research_plan"]
    assert plan["status"] == "unavailable" and not plan["tickets"]
    assert plan["total_stake_yen"] == 0
    assert "実オッズが未取得" in plan["reason"]
    assert "02-08" in workflow.render(payload)
    assert payload["prediction_json"]["marks"]["08"] == "◎"


def test_scout_payload_does_not_generate_virtual_tickets(workflow, priced_sample):
    """全日探索用の出力では、個別予想用の仮想プランを生成しない。"""
    model, forecast, snapshot, now = priced_sample
    payload = workflow.build_payload(model, forecast, snapshot, now, research_prediction=False)
    assert "research_plan" not in payload["prediction_json"]
    assert payload["prediction_tickets"] == []


def test_saved_virtual_plan_evaluates_without_actual_spend(workflow, priced_sample, tmp_path):
    """事前保存・結果照合・評価読戻しで仮想収支を保持し、実購入集計を0円に保つ。"""
    from jra_srb.analysis_store import AnalysisSQLiteStore
    from jra_srb.models import RaceResult, ResultEntry, PayoutEntry
    model, forecast, snapshot, now = priced_sample
    payload = workflow.build_payload(model, forecast, snapshot, now)
    payload["prediction_json"]["presentation_markdown"] = workflow.render(payload)
    store = AnalysisSQLiteStore(tmp_path / "research-contract.sqlite")
    store.upsert_prediction_record(payload)
    assert store.get_prediction_record(payload["prediction_id"]).prediction == payload["prediction_json"]
    store.write_result(RaceResult(race_id=payload["race_id"], race_name="隔離研究評価",
        results=[ResultEntry(rank="1", horse_no="8", horse_name="8"),
                 ResultEntry(rank="2", horse_no="2", horse_name="2"),
                 ResultEntry(rank="3", horse_no="1", horse_name="1")],
        payouts=[PayoutEntry(bet_type="馬連", combination="8-2", payout="1000")],
        fetched_at=now, source="isolated-fixture"))
    store.evaluate_prediction_record({"prediction_id": payload["prediction_id"], "evaluation_id": "research-eval"})
    saved = store.get_evaluation_record("research-eval")
    virtual = saved.evaluation["summary"]["research_simulation"]
    assert virtual["hit"] is True and virtual["virtual_only"]
    assert virtual["virtual_stake_yen"] == 1000 and virtual["virtual_payout_yen"] == 5000
    assert virtual["virtual_return_rate"] == 5.0 and len(virtual["ticket_results"]) == 3
    assert saved.total_bet == saved.total_payout == 0 and not saved.ticket_results
    assert saved.evaluation["summary"]["winner_hit"] is None


def test_virtual_missing_payout_loss_and_reconstruction(workflow, priced_sample):
    """払戻不足を不的中にせず、確定した不的中と事後復元を区別する。"""
    from jra_srb.analysis_store import _evaluate_research_plan
    model, forecast, snapshot, now = priced_sample
    prediction = workflow.build_payload(model, forecast, snapshot, now)["prediction_json"]
    assert _evaluate_research_plan(prediction, {})["status"] == "unavailable"
    lost = _evaluate_research_plan(prediction, {("quinella", "1-2"): 1000})
    assert lost["hit"] is False and lost["virtual_return_rate"] == 0
    prediction["reconstruction_after_result"] = True
    assert _evaluate_research_plan(prediction, {("quinella", "2-8"): 1000})["status"] == "unavailable"
    prediction.pop("research_plan")
    assert _evaluate_research_plan(prediction, {}) is None
