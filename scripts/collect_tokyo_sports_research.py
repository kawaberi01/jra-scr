"""概要: 東スポ杯2歳Sの固定過去年と公式当年入力を有界取得・照合する。
作成日: 2026-11-22
入力: export/collect、出力先、研究readerの環境設定。
出力: 対象23開催と事前履歴、RA根拠、公式12頭の監査済み入力。
実行例: uv run python scripts/collect_tokyo_sports_research.py export --output artifacts/jra_research/tospo_history_v1
注意事項: readerはSELECTのみ。公式通信あり。当該2026年結果は取得しない。
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import httpx
from bs4 import BeautifulSoup
from jra_srb.extractors import _parse_jra_race_card
from jra_srb.provider import HttpProvider
from jra_srb.jra_race_conditions_sql import ConditionsReader, normalize_row
from run_jra_graded_live import official, header_conditions, recent_comparisons
from audit_elizabeth_2026_inputs import parse_history


def save(path: Path, value: object) -> None:
    """照合可能なJSONを新規保存する。"""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def config() -> dict:
    """既存readerの非秘密設定を再利用する。"""
    return json.loads((ROOT / "configs/research/race_conditions_elizabeth_v1.json").read_text(encoding="utf-8"))


def metadata(reader: ConditionsReader, keys: list[str]) -> dict:
    """必要な競走だけhashと完全キーで取得する。"""
    result = {}
    for start in range(0, len(keys), 64):
        chunk = keys[start:start+64]
        values = ",".join("(CONVERT(binary(32),?),CONVERT(nvarchar(max),?))" for _ in chunk)
        params = [v for key in chunk for v in (hashlib.sha256(key.encode("utf-16le")).digest(), key)]
        rows = reader.rows("tospo:metadata", "SELECT r.race_key,CONVERT(varchar(10),r.race_date,23) race_date,"
            "r.venue_code,r.retrospective_metadata_json metadata FROM history.races r JOIN (VALUES "+values+") k(h,key_value) "
            "ON r.__unified_race_sha256=k.h AND r.race_key=k.key_value WHERE r.__migration_source_snapshot_id=31", params, 64)
        result.update({r["race_key"]: r for r in rows})
    return result


def export(folder: Path) -> None:
    """同名23年と各馬の対象日前の履歴だけを取得しRAと照合する。"""
    with ConditionsReader(config()) as reader:
        preflight = reader.preflight()
        targets = reader.rows("tospo:targets", "SELECT TOP(30) race_key,CONVERT(varchar(10),race_date,23) race_date,"
            "venue_code,retrospective_metadata_json metadata,__unified_race_sha256 race_hash FROM history.races "
            "WHERE __migration_source_snapshot_id=31 AND race_date>='2003-01-01' AND race_date<'2026-01-01' "
            "AND JSON_VALUE(retrospective_metadata_json,'$.race_name') IN (?,?) ORDER BY race_date",
            ("東京スポーツ杯２歳ステークス", "東京スポーツ杯2歳ステークス"), 30)
        assert len(targets) == 23 and {t["race_date"][:4] for t in targets} == {str(y) for y in range(2003,2026)}
        raw_rows = reader.target_entries(targets)
        rows = [normalize_row(r) | {"historical_popularity_raw": json.loads(r["attrs"]).get("popularity"),
                                      "source_attrs": json.loads(r["attrs"])} for r in raw_rows]
        cutoff = {r["horse_id"]: r["race_date"].replace("-", "") for r in rows}
        ids = sorted(cutoff)
        values = ",".join("(CONVERT(nvarchar(10),?),CONVERT(nvarchar(12),?))" for _ in ids)
        params = [v for hid in ids for v in (hid,cutoff[hid]+"0000")]
        entries = reader.rows("tospo:entries_before_target", "SELECT TOP(4001) e.race_key,e.horse_id,e.horse_no,e.rank,e.abnormal_code,"
            "e.retrospective_se_json attrs FROM history.entries e JOIN (VALUES "+values+") h(id,cutoff_key) "
            "ON CONVERT(nvarchar(10),e.horse_id)=h.id WHERE e.__migration_source_snapshot_id=31 "
            "AND CONVERT(nvarchar(12),e.race_key)<h.cutoff_key OPTION (HASH JOIN)", params, 4000)
        keys = sorted({r["race_key"] for r in entries})
        meta = metadata(reader, keys)
        assert set(meta) == set(keys)
        history = [normalize_row({**r, **meta[r["race_key"]]}) for r in entries]
        conditions, audit = reader.race_conditions(set(keys) | {t["race_key"] for t in targets})
        for row in rows+history:
            cond = conditions.get(row["race_key"])
            assert cond and row["distance"] == int(cond["distance_raw"]) and row["track_code"] == cond["track_code"]
            row.update(ra_verified=True, conditions_verified=True, **{k:cond[k] for k in ("grade","weight_rule","symbol","condition_code")})
        races = []
        for target in targets:
            m = json.loads(target["metadata"])
            assert target["venue_code"] == "05" and m["distance_raw"] == "1800" and m["track_code"] == "11"
            active = [r for r in rows if r["race_key"] == target["race_key"] and r["status"] == "active"]
            assert sum(bool(r["rank"] and r["rank"] <= 3) for r in active) == 3
            assert all(r["age"] == 2 for r in active)
            races.append({k:target[k] for k in ("race_key","race_date","venue_code")} | {"race_name":"東京スポーツ杯2歳ステークス",
                "distance":1800,"track_code":"11","grade":conditions[target["race_key"]]["grade"],"runners":active})
        save(folder / "dataset.json", {"races":races,"history":history,"provenance":preflight,
            "historical_attributes":"retrospective","historical_non_jra_coverage":"incomplete"})
        save(folder / "ra-audit.json", audit)
        save(folder / "sql-preflight.json", preflight)
        save(folder / "query-metrics.json", reader.query_metrics)
        print(json.dumps({"races":len(races),"runners":len(rows),"history":len(history),"verified_ra":len(conditions)}))


async def collect(folder: Path) -> None:
    """公式出馬表12頭と全掲載成績をID・実近走で照合する。"""
    provider = HttpProvider(retries=0, min_interval_seconds=1)
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=60) as client:
        response = client.get("/meetings/2026-11-23/tokyo/races/11/card", params={"refresh":"true"})
        response.raise_for_status()
        api = response.json()
    save(folder / "api-card.json", api)
    assert api["race_id"] == "202611230511" and len(api["runners"]) == 12
    raw = await official(provider, api["source"], folder / "card-source.html")
    soup = BeautifulSoup(raw,"html.parser")
    parsed = _parse_jra_race_card(soup)
    parsed["runners"] = [r.model_dump(mode="json") if hasattr(r,"model_dump") else r for r in parsed["runners"]]
    save(folder / "parsed-card.json", parsed)
    assert [r["horse_name"] for r in parsed["runners"]] == [r["horse_name"] for r in api["runners"]]
    runners, profiles, audits = [],[],[]
    (folder / "profiles").mkdir(exist_ok=True)
    for row in parsed["runners"]:
        assert row["status"] == "active"
        links = {a["href"] for a in soup.find_all("a",href=True) if a.get_text("",strip=True) == row["horse_name"] and re.search(r"pw01dud00\d{10}/",a["href"])}
        assert len(links) == 1
        href = next(iter(links)); hid = re.search(r"pw01dud00(\d{10})/",href)[1]
        html = await official(provider,href,folder / "profiles" / (hid+".html"))
        assert row["horse_name"] in BeautifulSoup(html,"html.parser").get_text() and hid[:4] == "2024"
        history = parse_history(html,hid,"2026-11-23")
        comparisons = recent_comparisons(row,history)
        assert history and all(c["status"] == "matched" for c in comparisons)
        assert all(h["race_key"] for h in history),"non_JRA_requires_explicit_adapter"
        assert row["sex_age"].startswith(("牡2/","牝2/"))
        runners.append({"horse_no":str(int(row["horse_no"])),"horse_name":row["horse_name"],"horse_id":hid,"age":2,
            "sex":"2" if row["sex_age"].startswith("牝") else "1","frame_no":int(row["frame_no"]),
            "weight_carried":float(row["weight_carried"].split()[0]),"status":"active"})
        profiles.extend(history)
        audits.append({"horse_no":row["horse_no"],"horse_id":hid,"comparisons":comparisons,"profile_rows":len(history)})
        print(json.dumps({"horse_no":row["horse_no"],"profile_rows":len(history)}),flush=True)
    keys = sorted({h["race_key"] for h in profiles})
    with ConditionsReader(config()) as reader:
        save(folder / "sql-preflight.json",reader.preflight())
        conditions,audit = reader.race_conditions(set(keys))
        meta = metadata(reader,keys)
    normalized=[]
    for key in keys:
        example = next(h for h in profiles if h["race_key"] == key)
        fields = {**conditions[key],"race_name":json.loads(meta[key]["metadata"])["race_name"]} if key in conditions and key in meta else header_conditions(await official(provider,example["source_url"],folder / (key+".html")))
        for h in [v for v in profiles if v["race_key"] == key]:
            assert h["distance"] == int(fields["distance_raw"]) and h["weight_carried"] is not None
            normalized.append({"race_key":key,"race_date":h["race_date"],"race_name":fields["race_name"],"horse_id":h["horse_id"],
                "venue_code":key[8:10],"distance":h["distance"],"track_code":fields["track_code"],"rank":h["rank"],
                "weight_carried":h["weight_carried"],"status":"excluded" if h["rank_raw"] in ("取消","除外") else "active",
                "conditions_verified":True,"ra_verified":key in conditions,
                **{k:fields[k] for k in ("grade","weight_rule","symbol")},"condition_code":fields.get("condition_code")})
    save(folder / "normalized-card.json",{"race_key":api["race_id"],"race_date":"2026-11-23","race_name":"東京スポーツ杯2歳ステークス",
        "venue_code":"05","distance":1800,"track_code":"11","start_at":"2026-11-23T15:30:00+09:00","observed_at":api["fetched_at"],"runners":runners})
    save(folder / "normalized-history.json",normalized)
    save(folder / "profile-history.json",profiles)
    save(folder / "input-audit.json",audits)
    save(folder / "ra-audit.json",audit)


def main() -> None:
    """未使用出力先を用い、失敗は証跡を残して停止する。"""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("export","collect"))
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    try:
        export(args.output) if args.command == "export" else asyncio.run(collect(args.output))
        save(args.output / "manifest.json",{"completed_at":datetime.now(timezone.utc).isoformat(),
            "files":{str(p.relative_to(args.output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.rglob("*") if p.is_file()}})
    except Exception as error:
        save(args.output / "failure.json",{"stage":args.command,"type":type(error).__name__,"reason":getattr(error,"reason",str(error) if isinstance(error,(AssertionError,ValueError)) else "collection_failed")})
        raise


if __name__ == "__main__":
    main()
