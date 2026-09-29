#!/usr/bin/env python3
import json
from pathlib import Path
import pandas as pd
import requests
OUT=Path('output'); OUT.mkdir(exist_ok=True)
URL='https://kind.krx.co.kr/corpgeneral/corpList.do?method=download'
def main():
 r=requests.get(URL,headers={'User-Agent':'Mozilla/5.0'},timeout=30); r.raise_for_status(); tmp=OUT/'kind.xlsx'; tmp.write_bytes(r.content)
 df=pd.read_excel(tmp,dtype=str); tmp.unlink(missing_ok=True)
 code=next(c for c in df.columns if '종목코드' in c); sector=next((c for c in df.columns if '업종' in c),None); name=next((c for c in df.columns if '회사명' in c),None)
 out={str(r[code]).zfill(6):{'sector':str(r[sector]).strip() if sector and pd.notna(r[sector]) else '미분류','name':str(r[name]).strip() if name and pd.notna(r[name]) else ''} for _,r in df.iterrows() if pd.notna(r[code])}
 (OUT/'sector_map_kr.json').write_text(json.dumps(out,ensure_ascii=False,separators=(',',':')),encoding='utf-8'); print('wrote',len(out))
if __name__=='__main__': main()
