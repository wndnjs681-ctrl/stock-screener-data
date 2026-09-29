#!/usr/bin/env python3
import json,re,time
from pathlib import Path
import requests
from bs4 import BeautifulSoup
import FinanceDataReader as fdr
OUT=Path('output'); OUT.mkdir(exist_ok=True); H={'User-Agent':'Mozilla/5.0'}
def num(s):
 s=(s or '').replace(',','').replace('%','').strip()
 try:return float(s)
 except:return None
def main():
 ls=pd=None; frames=[]
 for m in ('KOSPI','KOSDAQ'):
  try: frames.append(fdr.StockListing(m))
  except Exception as e: print(m,e)
 import pandas as pd
 ls=pd.concat(frames).drop_duplicates('Code'); out={}; ses=requests.Session(); ses.headers.update(H)
 for i,r in ls.iterrows():
  code=str(r.Code).zfill(6)
  try:
   html=ses.get(f'https://finance.naver.com/item/main.naver?code={code}',timeout=15).text; soup=BeautifulSoup(html,'html.parser')
   def get(id):
    el=soup.find(id=id); return num(el.get_text(' ',strip=True)) if el else None
   out[code]={'name':str(r.Name),'forward_per':get('_cns_per'),'cns_eps':get('_cns_eps'),'per':get('_per'),'eps':get('_eps'),'pbr':get('_pbr'),'bps':get('_bps'),'dvr':get('_dvr')}
  except Exception as e: print('fail',code,e)
  if len(out)%100==0: print(len(out)); time.sleep(.4)
 (OUT/'consensus_kr.json').write_text(json.dumps(out,ensure_ascii=False,separators=(',',':')),encoding='utf-8'); print('wrote',len(out))
if __name__=='__main__': main()
