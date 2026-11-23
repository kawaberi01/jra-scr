"""概要: 固定配布台帳の必要な公式成績だけを通常readerで取り込み値SHAを照合する。
作成日: 2026-11-22
入力: --provider-root、--package、--dataset、--history、--card、--env-file、--output。
出力: facts.json、対応監査、台帳/入力/出力SHA。異常時failure.jsonと非0。
実行例: uv run python scripts/export_mile_official_materials.py --help
注意事項: SELECTのみ。取得側コードを再利用し、原本・DB・既存予想を変更しない。
"""

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import unicodedata
import zipfile


def read(path):
    """UTF-8 JSONを読む。"""
    return json.loads(path.read_text(encoding="utf-8"))


def save(path,value):
    """新規JSONにだけ出力する。"""
    with path.open("x",encoding="utf-8") as f:
        json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False)


def name(value):
    """同定済み行の氏名表記について空白と互換文字だけを正規化する。"""
    return "".join(unicodedata.normalize("NFKC",str(value or "")).split())


def main():
    """固定採用IDの成績全列と必要列の欠測理由を有界SELECTで取得する。"""
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ("provider-root","package","dataset","history","card","env-file","output"):
        parser.add_argument("--"+key,type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise ValueError("output_exists")
    args.output.mkdir(parents=True)
    try:
        sys.path.insert(0,str(args.provider_root/"src"))
        os.environ["JRA_SRB_STORAGE_ENV_FILE"]=str(args.env_file)
        from jra_srb.official_normalization import NormalizationStore,typed_values,sha,require
        from jra_srb.official_normalization_schema import FACTS
        from jra_srb.storage_config import SqlServerSettings
        dataset=read(args.dataset); current=read(args.history); card=read(args.card)
        keys={h["race_key"] for h in dataset["history"]+dataset["target_rows"]+current}
        with zipfile.ZipFile(args.package) as z:
            index=json.loads(z.read("package-index.json"))
            for item in index["files"]:
                content=z.read(item["path"])
                require(len(content)==item["bytes"] and hashlib.sha256(content).hexdigest()==item["sha256"],"package_sha")
            ledger=list(csv.DictReader(io.StringIO(z.read("typed/race-typed-coverage.csv").decode("utf-8-sig"))))
            editions={r["edition_id"]:{**r,"race_key":r["race_date"].replace("-","")+r["venue_code"].zfill(2)+r["race_no"].zfill(2)} for r in ledger
                if r["race_date"].replace("-","")+r["venue_code"].zfill(2)+r["race_no"].zfill(2) in keys}
            fixed=[r for r in json.loads(z.read("typed/current-records.json"))["records"] if r["edition_id"] in editions and r["record_kind"]=="runner_results"]
            fixed_by_id={r["record_id"]:r for r in fixed}
        require(0<len(fixed)<=10000,"official_export_limit")
        facts=[]; store=NormalizationStore(SqlServerSettings.from_env())
        with store.connection() as con:
            cursor=con.cursor()
            for start in range(0,len(fixed),100):
                ids=[r["record_id"] for r in fixed[start:start+100]]
                sql="SELECT n.record_id,n.edition_id,n.value_sha256,n.input_set_sha256,p.horse_name_raw,"+",".join("f.["+k+"]" for k in FACTS["runner_results"])+" FROM official_materials.normalized_records n JOIN official_materials.runner_results f ON f.record_id=n.record_id JOIN official_materials.participants p ON p.participant_id=n.participant_id WHERE n.record_id IN ("+",".join("?" for _ in ids)+")"
                cursor.execute(sql,tuple(ids)); columns=[d[0] for d in cursor.description]; fetched=[dict(zip(columns,r,strict=True)) for r in cursor.fetchall()]
                require(len(fetched)==len(ids),"official_missing_rows")
                for row in fetched:
                    identity=str(row["record_id"]).lower(); expected=fixed_by_id[identity]
                    values=typed_values("runner_results",{k:row[k] for k in FACTS["runner_results"]})
                    require(row["value_sha256"]==expected["value_sha256"]==sha(values) and row["input_set_sha256"]==expected["input_set_sha256"],"official_value_sha")
                    edition=editions[str(row["edition_id"]).lower()]
                    facts.append({"record_id":identity,"race_key":edition["race_key"],"horse_name":row["horse_name_raw"],"values":values,"value_sha256":row["value_sha256"],"input_set_sha256":row["input_set_sha256"]})
            fields={}
            for start in range(0,len(fixed),100):
                ids=[r["record_id"] for r in fixed[start:start+100]]
                cursor.execute("SELECT record_id,field_name,value_state,missing_reason,transform_rule FROM official_materials.record_fields WHERE record_id IN ("+",".join("?" for _ in ids)+") AND field_name IN ('finish_time_seconds','final_3f_seconds','finish_rank')",tuple(ids))
                for rid,field,state,reason,rule in cursor.fetchall():
                    fields.setdefault(str(rid).lower(),{})[field]={"value_state":state,"missing_reason":reason,"transform_rule":rule}
            cursor.close()
        for f in facts:
            f["fields"]=fields[f["record_id"]]
            require(len(f["fields"])==3,"official_field_states")
        by_key={}
        for f in facts:by_key.setdefault(f["race_key"],[]).append(f)
        linked=[]; unavailable=[]
        current_names={r["horse_id"]:r["horse_name"] for r in card["runners"]}
        unique={}
        for r in dataset["history"]+dataset["target_rows"]+current:
            unique[(r["race_key"],r["horse_id"])]=r if r.get("horse_no") else unique.get((r["race_key"],r["horse_id"]),r)
        for r in unique.values():
            pool=by_key.get(r["race_key"],[])
            if not pool:continue
            if r.get("horse_no"):
                matches=[f for f in pool if f["values"]["horse_no"]==int(r["horse_no"])]
                method="race_and_horse_number_plus_name_rank_weight"
            else:
                matches=[f for f in pool if name(f["horse_name"])==name(current_names[r["horse_id"]]) and f["values"]["finish_rank"]==r.get("rank") and f["values"]["carried_weight_kg"] is not None and abs(float(f["values"]["carried_weight_kg"])-r["weight_carried"])<.001]
                method="verified_profile_id_plus_race_name_rank_weight"
            require(len(matches)==1,"official_identity_ambiguous_or_missing")
            f=matches[0]; v=f["values"]
            require(name(f["horse_name"])==name(r.get("horse_name") or current_names.get(r["horse_id"])) and v["finish_rank"]==r.get("rank"),"official_identity_name_rank")
            require(v["carried_weight_kg"] is not None and abs(float(v["carried_weight_kg"])-r["weight_carried"])<.001,"official_identity_weight")
            if r in dataset["target_rows"]:
                require(v["age"]==r["age"] and v["frame_no"]==r["frame_no"],"official_target_attributes")
            linked.append({"race_key":r["race_key"],"horse_id":r["horse_id"],"record_id":f["record_id"],"method":method})
        save(args.output/"facts.json",facts);save(args.output/"links.json",linked)
        save(args.output/"coverage.json",{"editions":len(editions),"facts":len(facts),"linked_history_identities":len(linked),"fields_with_reasons":sum(len(f["fields"]) for f in facts),"snapshot_status":"research_record_set_not_sealed_prediction_input"})
        inputs=[Path(__file__),args.package,args.dataset,args.history,args.card,args.provider_root/"src/jra_srb/official_normalization.py",args.provider_root/"src/jra_srb/official_normalization_schema.py"]
        save(args.output/"manifest.json",{"inputs":{str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},"outputs":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.iterdir() if p.is_file()}})
        print({"facts":len(facts),"links":len(linked),"editions":len(editions)})
    except Exception as error:
        save(args.output/"failure.json",{"type":type(error).__name__,"reason":str(error)})
        raise


if __name__=="__main__":main()
