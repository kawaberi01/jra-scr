from __future__ import annotations
import gzip,json
from collections import defaultdict
from pathlib import Path

H=[('consensus',1,3,1,3,2,10,0),('market2_3_model1',2,3,1,1,3,15,0),('market3_5_model2',3,5,1,2,4,15,.01),('market4_6_model1',4,6,1,1,5,20,.01),('market2_4_residual',2,4,1,2,3,12,.02),('market3_6_mid',3,6,1,3,5,20,.02),('market4_6_safe',4,6,1,3,3,12,.01),('market1_3_history',1,3,1,3,4,10,.01),('market3_4_exact',3,4,1,2,5,15,.01),('market5_6_leap',5,6,1,1,6,20,.02)]
def load(p):
 with gzip.open(p,'rt',encoding='utf8') as f:return [json.loads(x) for x in f]
def enrich(rows):
 d=defaultdict(list)
 for r in rows:d[r['race_id']].append(r)
 for rs in d.values():
  for i,r in enumerate(sorted(rs,key=lambda x:(-x['market_probability_normalized'],x['horse_no'])),1):r['mr']=i
  for i,r in enumerate(sorted(rs,key=lambda x:(-x['isotonic_probability'],x['horse_no'])),1):r['hr']=i
def score(rows,h):
 n,a,b,c,d,lo,hi,e=h; groups=defaultdict(list)
 for r in rows:
  if a<=r['mr']<=b and c<=r['hr']<=d and lo<=r['win_odds']<=hi and r['isotonic_probability']-r['market_probability_normalized']>=e:groups[r['race_id']].append(r)
 s=[max(x,key=lambda r:r['isotonic_probability']-r['market_probability_normalized']) for x in groups.values()]; p=sorted([x['win_payout'] if x['label_win'] else 0 for x in s],reverse=True)
 def roi(v):return sum(v)/(100*len(v)) if v else 0
 return {'candidates':len(s),'roi':roi(p),'no_max_roi':roi(p[1:]),'no_top3_roi':roi(p[3:])}
def main():
 root=Path('.workstate/jra-srb/jra-win-ev-revalidation/artifacts'); rows=load(root/'runner-predictions.jsonl.gz'); split=json.loads((root/'split-metadata.json').read_text(encoding='utf8'))['date_sets']; cal=[r for r in rows if r['race_date'] in set(split['calibration'])]; ext=[r for r in rows if r['race_date'] in set(split['external'])];enrich(cal);enrich(ext)
 out=[]
 for h in H:
  c,e=score(cal,h),score(ext,h);out.append({'hypothesis':h[0],'calibration':c,'external':e,'passed':e['candidates']>=100 and min(e['roi'],e['no_max_roi'],e['no_top3_roi'])>=1})
 p=Path('.workstate/jra-srb/jra-market-residual-validation');(p/'ten-hypotheses.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
