"""Public, read-only source inventory; save metadata, not copyrighted articles."""
from pathlib import Path
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
import httpx
from bs4 import BeautifulSoup

OUT = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding='utf-8')
TARGETS = [
    ('20250105', '中山', '中山金杯'), ('20250105', '中京', '京都金杯'),
    ('20250112', '中山', 'フェアリー'), ('20250113', '中京', 'シンザン'),
    ('20250119', '中山', '京成杯'), ('20250119', '中京', '日経新春'),
    ('20250125', '小倉', '小倉牝馬'), ('20250126', '中山', 'AJCC'),
    ('20250126', '中京', 'プロキオン'), ('20250202', '東京', '根岸'),
]
NOTE_KEYS = ['n6be5b403170b','n4f5b071cb23d','na5a8dadb9be0','n270aa29ccb97',
             'nd261a78cb4f1','nfc2f13739dfa','nfc9a609f7bc0','ndf2117c03abb',
             'n697f118ebcbf','nefb678ec560f']

def collect_details():
    inventory = json.loads((OUT/'expansion_inventory.json').read_text(encoding='utf-8'))
    items = [x for day in inventory for x in day.get('races',[]) if x['selected']]
    details = []
    with httpx.Client(timeout=30,follow_redirects=True) as client:
        for item in items:
            response = client.get(item['url'])
            response.raise_for_status()
            soup = BeautifulSoup(response.content,'html.parser',from_encoding='euc-jp')
            body = soup.select_one('.YosoKenkaiTxt')
            if body is None or not body.get_text(strip=True):
                raise ValueError('Public reasoning not readable: '+item['url'])
            types = {}
            table = soup.select_one('.YosoKaimeTable01')
            if table is None:
                raise ValueError('Public tickets not readable: '+item['url'])
            for row in table.select('tbody > tr'):
                th = row.find('th')
                kind = th.find(string=True,recursive=False).strip()
                pat = row.select_one('.BuyPatern').get_text(' ',strip=True)
                count_match = re.search(r'(\d+)通り',pat)
                count = int(count_match[1]) if count_match else 1
                amount = int(re.findall(r'([\d,]+)円',pat)[-1].replace(',',''))
                refund = sum(int(x.get_text(strip=True).replace(',','').replace('円','')) for x in row.select('.BakenRefund strong'))
                total = types.setdefault(kind,dict(stake_yen=0,return_yen=0,ticket_count=0))
                total['stake_yen'] += count*amount
                total['return_yen'] += refund
                total['ticket_count'] += count
            display_nums = [int(x.replace(',','')) for x in re.findall(r'([\d,]+)\s*円',item['balance_display'])]
            assert sum(x['stake_yen'] for x in types.values()) == display_nums[0],item
            assert sum(x['return_yen'] for x in types.values()) == display_nums[1],item
            details.append(dict(**item,access='public_reasoning_and_tickets',
                                response_sha256=hashlib.sha256(response.content).hexdigest(),
                                ticket_type_totals=types))
            print(item['person'],item['race_name'],types,flush=True)
        for (date,course,race),key in zip(TARGETS,NOTE_KEYS,strict=True):
            url='https://note.com/yamaguchiyoshino/n/'+key
            response=client.get(url)
            response.raise_for_status()
            soup=BeautifulSoup(response.content,'html.parser')
            article=soup.select_one('article')
            body=article.get_text(' ',strip=True) if article else ''
            assert '2025年' in body and '全馬解説' in body and '買い目は公開していません' in body,url
            details.append(dict(person='山口吉野',date=date,course=course,race_name=race,
                                url=url,access='public_reasoning_probability_image_no_tickets',
                                response_sha256=hashlib.sha256(response.content).hexdigest(),
                                title=soup.title.get_text(strip=True),ticket_type_totals=None,
                                probability_transcribed=False))
    (OUT/'expansion_sources.json').write_text(json.dumps(details,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def main():
    protocol = {
        'created_at': datetime.now(timezone.utc).isoformat(),
        'selection': '2025年初めの連続する10重賞。追加本文と収支の取得前に対象を固定。初回9例と検索段階の一部結果は既知であり完全な事前登録ではない。',
        'targets': [dict(date=d, course=c, race_match=n) for d, c, n in TARGETS],
        'persons': ['YUTA', 'キムラヨウヘイ', '山口吉野'],
        'missing_policy': '未公開・取得失敗・買い目非公開を区別。代替成功例を補充しない。',
        'timing_policy': '現在の公開ページと表示時刻。発走前保存版や変更履歴を独立確認していない。',
    }
    protocol_path = OUT / 'expansion_protocol.json'
    if not protocol_path.exists():
        protocol_path.write_text(json.dumps(protocol, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    records = []
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for person, person_id in [('YUTA', '472'), ('キムラヨウヘイ', '284')]:
            for date in sorted({d for d, _, _ in TARGETS}):
                params = dict(pid='api_get_goods_list_prof', input='UTF-8', output='jsonp',
                              show_id='yoso_view', cond_type='y', yosoka_id=person_id,
                              kaisai_date=date, jyo='all')
                try:
                    response = client.post('https://yoso.netkeiba.com/', data=params)
                    response.raise_for_status()
                    raw = response.text.strip().removesuffix(';')
                    html = json.loads(raw[raw.index('(')+1:raw.rindex(')')])
                    soup = BeautifulSoup(html, 'html.parser')
                    day_records = []
                    for row in soup.select('li[id^="goods_state_"]'):
                        race = row.select_one('.YosoRace')
                        if race is None:
                            continue
                        def val(selector):
                            node = row.select_one(selector)
                            return node.get_text(' ', strip=True) if node else None
                        ident = row['id'].removeprefix('goods_state_')
                        item = dict(person=person, date=date, course=val('.YosoRace .Jyo'),
                                    race_no=val('.YosoRace .Num'), race_name=val('.YosoRace .Name'),
                                    url=f'https://yoso.sp.netkeiba.com/?id={ident}&pid=yoso_detail',
                                    published_display=val('.YosoDetailSec'), balance_display=val('.BalanceArea'),
                                    selected=any(date==d and val('.YosoRace .Jyo')==c and val('.YosoRace .Num')=='11R' for d,c,_ in TARGETS))
                        day_records.append(item)
                    records.append(dict(person=person,date=date,source_params=params,
                                        response_sha256=hashlib.sha256(response.content).hexdigest(),
                                        races=day_records, status='ok'))
                    print(person,date,len(day_records),flush=True)
                except Exception as exc:
                    records.append(dict(person=person,date=date,status='error',error=str(exc)))
                    print(person,date,type(exc).__name__,flush=True)
    (OUT/'expansion_inventory.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

if __name__ == '__main__':
    if '--details' in sys.argv:
        collect_details()
    else:
        main()
