"""概要: 札幌2歳Sの固定公式資料を東スポ杯の補助根拠として読み出す。
作成日: 2026-11-22
入力: 配布1.2ZIP、通常reader環境設定、既存照合リンク。
出力: 型付き値・列別状態・出典・補助解説とSHA。
実行例: uv run python scripts/export_tokyo_sports_official_context.py
注意事項: SELECTのみ。11/23対象結果は取得せず、資料で主スコアを加点しない。
"""

import hashlib
import json
import os
from pathlib import Path
import sys
import zipfile


def main() -> None:
    """固定採用IDの値SHAを照合し、ラップ・位置・文章を分離保存する。"""
    provider=Path('D:/develop/jra-scr-data-import-visual-check')
    sys.path.insert(0,str(provider/'src'))
    os.environ['JRA_SRB_STORAGE_ENV_FILE']='D:/develop/jra-scr/data/storage/runtime.env'
    from jra_srb.official_normalization import NormalizationStore, typed_values, sha
    from jra_srb.official_normalization_schema import FACTS
    from jra_srb.storage_config import SqlServerSettings
    package=provider/'artifacts/handoff/jra-official-materials-consumer-v1.2-20261121.zip'
    folder=Path('artifacts/jra_research/tokyo_sports_official_context_20261122_v1');folder.mkdir(exist_ok=False)
    with zipfile.ZipFile(package) as z:
        index=json.loads(z.read('package-index.json'))
        for item in index['files']:assert hashlib.sha256(z.read(item['path'])).hexdigest()==item['sha256']
        fixed=[r for r in json.loads(z.read('typed/current-records.json'))['records'] if r['edition_id']=='2188cb2e-f2bf-5869-b40d-a6c8b09905b7']
    store=NormalizationStore(SqlServerSettings.from_env());out=[]
    with store.connection() as con:
        cursor=con.cursor()
        for expected in fixed:
            kind=expected['record_kind'];assert kind in FACTS
            cursor.execute('SELECT n.record_id,n.value_sha256,n.input_set_sha256,p.horse_name_raw,'+','.join('f.['+k+']' for k in FACTS[kind])+' FROM official_materials.normalized_records n JOIN official_materials.'+kind+' f ON f.record_id=n.record_id LEFT JOIN official_materials.participants p ON p.participant_id=n.participant_id WHERE n.record_id=?',(expected['record_id'],))
            names=[c[0] for c in cursor.description];rows=[dict(zip(names,r,strict=True)) for r in cursor.fetchall()];assert len(rows)==1
            row=rows[0];values=typed_values(kind,{k:row[k] for k in FACTS[kind]})
            assert sha(values)==row['value_sha256']==expected['value_sha256'] and row['input_set_sha256']==expected['input_set_sha256']
            cursor.execute('SELECT field_name,value_state,missing_reason,transform_rule FROM official_materials.record_fields WHERE record_id=?',(expected['record_id'],))
            fields={r[0]:{'value_state':r[1],'missing_reason':r[2],'transform_rule':r[3]} for r in cursor.fetchall()}
            assert all(k in fields for k in FACTS[kind])
            out.append({'record_id':expected['record_id'],'record_kind':kind,'horse_name':row['horse_name_raw'],'values':values,'fields':fields,'value_sha256':row['value_sha256'],'input_set_sha256':row['input_set_sha256']})
        cursor.close()
    (folder/'records.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    summary={'edition':'202609050111','record_counts':{kind:sum(r['record_kind']==kind for r in out) for kind in sorted({r['record_kind'] for r in out})},
        'target_past_editions_in_fixed_package':0,'linked_current_horses':['3 テンカタイヘイ','10 ショウナンガレオン'],
        'used_in_score':False,'use':'対象日前の前哨戦の時計差・末脚・位置取り・競走ラップを補助説明。歴年東スポ杯の同特徴充足なし。新スコアの有効性を実証したとしない。',
        'snapshot_status':'research_fixed_record_set_not_sealed_prediction_input'}
    (folder/'coverage.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'manifest.json').write_text(json.dumps({'package_sha256':hashlib.sha256(package.read_bytes()).hexdigest(),'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}},indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))
    print(json.dumps([r for r in out if r['horse_name'] in ('テンカタイヘイ','ショウナンガレオン') and r['record_kind']=='runner_results'],ensure_ascii=False))


if __name__=='__main__':main()
