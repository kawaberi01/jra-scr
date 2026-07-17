from __future__ import annotations
import argparse
import gzip,json
from collections import defaultdict
from pathlib import Path

# name, feature-index, mechanism; each runs ten pre-fixed thresholds.
THEORIES=[('experience',8,'経験量'),('distance_fit',18,'距離適性'),('surface_fit',16,'馬場適性'),('course_fit',14,'コース適性'),('jockey_win',20,'騎手勝率'),('jockey_top3',21,'騎手複勝率'),('trainer_win',23,'厩舎勝率'),('trainer_top3',24,'厩舎複勝率'),('finish_strength',12,'過去着順強度'),('horse_top3',11,'馬の通算複勝率')]
THRESHOLDS=(0.05,0.08,0.10,0.12,0.15,0.18,0.20,0.25,0.30,0.35)
def load(p):
 with gzip.open(p,'rt',encoding='utf8') as f:return [json.loads(x) for x in f]
def select(rows,index,t):
 d=defaultdict(list)
 for r in rows:
  v=r['features'][index]
  if 3<=r['win_odds']<=15 and v>=t:d[r['race_id']].append((v,r))
 return [max(x,key=lambda z:z[0])[1] for x in d.values()]
def met(rows):
 p=sorted([r['win_payout'] if r['label_win'] else 0 for r in rows],reverse=True)
 def roi(x):return sum(x)/(100*len(x)) if x else 0
 return {'candidates':len(p),'roi':roi(p),'no_max_roi':roi(p[1:]),'no_top3_roi':roi(p[3:])}
def main():
 parser=argparse.ArgumentParser(description='Evaluate ten pre-defined structural hypotheses.')
 parser.add_argument('--artifacts-dir',type=Path,default=Path('.workstate/jra-srb/jra-win-ev-revalidation/artifacts'))
 parser.add_argument('--output-dir',type=Path,default=Path('.workstate/jra-srb/jra-structural-hypotheses'))
 args=parser.parse_args()
 root=args.artifacts_dir; rows=load(root/'runner-predictions.jsonl.gz'); split=json.loads((root/'split-metadata.json').read_text(encoding='utf8'))['date_sets'];cal=[r for r in rows if r['race_date'] in set(split['calibration'])];ext=[r for r in rows if r['race_date'] in set(split['external'])]
 results=[]
 for name,index,mechanism in THEORIES:
  its=[]
  for t in THRESHOLDS:its.append({'threshold':t,'calibration':met(select(cal,index,t))})
  viable=[x for x in its if x['calibration']['candidates']>=100]
  chosen=max(viable,key=lambda x:(x['calibration']['no_top3_roi'],x['calibration']['no_max_roi'],x['calibration']['roi'])) if viable else None
  external=met(select(ext,index,chosen['threshold'])) if chosen else None
  passed=bool(external and external['candidates']>=100 and min(external['roi'],external['no_max_roi'],external['no_top3_roi'])>=1)
  results.append({'theory':name,'mechanism':mechanism,'iterations':its,'chosen':chosen,'external':external,'passed':passed})
 out=args.output_dir;out.mkdir(parents=True,exist_ok=True);(out/'ten-structural-hypotheses.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 lines=['# 構造仮説10本 × 閾値10反復','']
 for r in results:lines.append(f"- {r['theory']}（{r['mechanism']}）: chosen={r['chosen']} external={r['external']} pass={r['passed']}")
 (out/'ten-structural-hypotheses.md').write_text('\n'.join(lines)+'\n',encoding='utf8');print('STRUCTURAL_STATUS=completed passes='+str(sum(r['passed'] for r in results)))
if __name__=='__main__':main()
