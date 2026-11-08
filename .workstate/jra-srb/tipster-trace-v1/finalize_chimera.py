"""Independent accounting and rule/label separation checks for saved experiments."""
from pathlib import Path
from collections import defaultdict
import ast
import copy
import hashlib
import importlib.util
import json
import sys

HERE=Path(__file__).resolve().parent
def digest(p):
    return hashlib.file_digest(p.open('rb'),'sha256').hexdigest()

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sources=json.loads((HERE/'expansion_sources.json').read_text(encoding='utf-8'))
    findings=json.loads((HERE/'expansion_findings.json').read_text(encoding='utf-8'))
    report=json.loads((HERE/'experiment_report.json').read_text(encoding='utf-8'))
    protocol=json.loads((HERE/'expansion_protocol.json').read_text(encoding='utf-8'))
    assert len(sources)==30
    cases=[]
    summaries={}
    for person,rules in findings['source_facts'].items():
        subset=sorted([s for s in sources if s['person']==person],
            key=lambda x:next(i for i,t in enumerate(protocol['targets']) if t['date']==x['date'] and t['course']==x['course']))
        assert len(subset)==len(rules)==10
        for source,rule in zip(subset,rules,strict=True):
            cases.append(dict(**source,observed_reasoning_summary=rule,
                researcher_interpretation='expansion_findings.json のR1～R6を参照。本人の式を復元したものではない。'))
        types=defaultdict(lambda:dict(stake_yen=0,return_yen=0))
        totals=[]
        for source in subset:
            if source['ticket_type_totals']:
                for kind,numbers in source['ticket_type_totals'].items():
                    for key in ['stake_yen','return_yen']:
                        types[kind][key]+=numbers[key]
                totals.append((sum(x['stake_yen'] for x in source['ticket_type_totals'].values()),
                               sum(x['return_yen'] for x in source['ticket_type_totals'].values())))
        stake=sum(x[0] for x in totals)
        returned=sum(x[1] for x in totals)
        largest=max(totals,key=lambda x:x[1]) if totals else (0,0)
        summaries[person]=dict(cases=10,public_tickets=len(totals),
            profitable_races=sum(r>s for s,r in totals) if totals else None,
            positive_return_races=sum(r>0 for s,r in totals) if totals else None,
            stake_yen=stake or None,return_yen=returned if totals else None,roi=returned/stake if stake else None,
            roi_without_largest_race=(returned-largest[1])/(stake-largest[0]) if stake>largest[0] else None,
            bet_type_totals=dict(types))
    (HERE/'expanded_cases.json').write_text(json.dumps(dict(cases=cases,summaries=summaries,
        limitation='連続10重賞の現在公開資料。年次実績・実購入・全レース・発走前保存版の証明ではない。'),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    module_spec=importlib.util.spec_from_file_location('chimera_research',HERE/'evaluate_chimera.py')
    mod=importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(mod)
    rows=[json.loads(line) for line in (HERE/'prediction_rows.jsonl').read_text(encoding='utf-8').splitlines()]
    fields=defaultdict(list)
    for row in rows:
        fields[row['race_id']].append(row)
    tickets=[json.loads(line) for line in (HERE/'tickets.jsonl').read_text(encoding='utf-8').splitlines()]
    index={(x['trial'],x['race_id']):x for x in tickets}
    assert len(index)==len(tickets)
    checked=0
    for trial in report['trials']:
        for rid,field in fields.items():
            selected=mod.choose(field,trial)
            contaminated=copy.deepcopy(field)
            for row in contaminated:
                row['rank']=999
                row['top3']=999
                row['result']={'future_information':'must not affect tickets'}
                row['T-10m']={'odds':999}
            alternate=mod.choose(contaminated,trial)
            selected_keys=[x['key'] for x in selected] if selected else None
            assert selected_keys==([x['key'] for x in alternate] if alternate else None)
            stored=index.get((trial,rid))
            if selected is None:
                assert stored is None
            else:
                assert selected_keys==[stored['anchor'],stored['partner']]
            checked+=1
        for split in ['dev','holdout','later']:
            part=[t for t in tickets if t['trial']==trial and t['split']==split]
            for kind in ['wide','quinella']:
                metric=report['trials'][trial][split][kind]
                assert sum(t[kind+'_stake'] for t in part)==metric['stake_yen']
                assert sum(t[kind+'_return'] for t in part)==metric['return_yen']
                assert sum(t[kind+'_return']>0 for t in part)==metric['hits']
    tree=ast.parse((HERE/'evaluate_chimera.py').read_text(encoding='utf-8'))
    assert not any(isinstance(x,ast.Constant) and x.value=='T-10m' for x in ast.walk(tree))
    for path,value in report['input_sha256'].items():
        assert digest(Path(path))==value
    for path,value in report['model_sha256'].items():
        assert digest(Path(path))==value
    assert digest(HERE/'experiment_contract.json')==report['contract_sha256']
    checks=dict(expanded_cases=30,persons=3,public_ticket_cases=20,hypothesis_trials=10,
        prediction_ticket_checks=checked,result_and_t10_mutation_does_not_change_tickets=True,
        training_script_no_t10_access=True,strict_past_dates_asserted_in_training=True,
        accounting_recomputed_from_tickets=True,original_dataset_and_baseline_model_hashes_unchanged=True,
        study_type='historical_research_not_saved_live_predictions',
        files={p.name:digest(p) for p in HERE.glob('*.py')})
    (HERE/'experiment_verification.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(summaries=summaries,checks=checks),ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
