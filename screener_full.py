#!/usr/bin/env python3
"""KR/US stock screener data builder.
GitHub Actions collects market data; Artifact consumes only generated JSON.
"""
from __future__ import annotations
import argparse, json, math, os, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
try:
 import FinanceDataReader as fdr
except ImportError:
 fdr=None

OUT=Path('output'); OUT.mkdir(exist_ok=True)
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36'

SCHEMA=[
 {'key':'close','label':'종가','type':'number','unit':'price','group':'기본','better':None,'decimals':2},
 {'key':'chg1d','label':'전일대비','type':'number','unit':'%','group':'기본','better':'high','decimals':2},
 {'key':'market_cap','label':'시가총액','type':'number','unit':'currency','group':'기본','better':'high','decimals':0},
 {'key':'amount','label':'거래대금','type':'number','unit':'currency','group':'기본','better':'high','decimals':0},
 {'key':'sector','label':'섹터','type':'text','unit':'','group':'기본','better':None,'decimals':0},
]

def add_num(k,l,u,g,b=None,d=2): SCHEMA.append({'key':k,'label':l,'type':'number','unit':u,'group':g,'better':b,'decimals':d})
def add_bool(k,l,g): SCHEMA.append({'key':k,'label':l,'type':'bool','unit':'','group':g,'better':'true','decimals':0})
for w in (20,60,120,252): add_num(f'hi_gap{w}',f'{w}일 고점대비','%','신고가','high',2); add_bool(f'is_hi{w}',f'{w}일 신고가','신고가')
add_num('lo_gap252','52주 저점대비','%','신고가','high',2); add_num('pos52w','52주 위치','%','신고가','high',1)
for w in (5,20,60,120): add_num(f'sma{w}',f'SMA {w}','price','이동평균',None,2); add_bool(f'above_ma{w}',f'{w}일선 위','이동평균')
add_bool('ma_bull','정배열','이동평균'); add_bool('ma_bear','역배열','이동평균'); add_num('ma_above_count','이평선 위 개수','개','이동평균','high',0)
add_num('dist_ma20','20일 이격도','%','이동평균',None,2); add_num('dist_ma60','60일 이격도','%','이동평균',None,2); add_num('ma20_slope','20일선 기울기(5일)','%','이동평균','high',2); add_bool('golden_5_20','골든크로스 5/20','이동평균')
add_num('vol_ratio20','거래량배수 20일','x','거래량','high',2); add_num('vol_ratio60','거래량배수 60일','x','거래량','high',2); add_num('vol_burst','Vol Burst','x','거래량','high',2); add_num('obv_pos','OBV 위치','%','거래량','high',1); add_bool('obv_high','OBV 신고가','거래량'); add_bool('obv_div','OBV 다이버전스','거래량')
for w in (5,20,60,120): add_num(f'ret{w}',f'{w}일 수익률','%','모멘텀','high',2)
add_num('rsi14','RSI(14)','점','모멘텀',None,1); add_num('green_streak','연속 양봉','일','모멘텀','high',0)
add_num('bb_upper','볼린저 상한(150,1.5)','price','변동성',None,2); add_num('bb_gap','볼린저 상한 대비','%','변동성','high',2); add_num('bb_pctb','%B','%','변동성',None,1); add_num('bb_width','밴드폭','%','변동성',None,2); add_num('atr20','ATR(20)','%','변동성',None,2)
for k,l in [('per','PER'),('pbr','PBR'),('roe','ROE'),('div_yield','배당수익률'),('forward_per','선행 PER'),('forward_eps','선행 EPS'),('eps_growth','EPS 증가율'),('sector_per_rel','업종 중앙값 대비 PER'),('sector_pbr_rel','업종 중앙값 대비 PBR'),('per_band_pos','52주 PER 밴드 위치')]: add_num(k,l,'%' if k in ('roe','div_yield','eps_growth','per_band_pos') else ('x' if 'per' in k or 'pbr' in k else 'currency'),'밸류에이션','low' if 'per' in k or 'pbr' in k else None,2)

def _finite(v):
 try:
  f=float(v); return f if math.isfinite(f) else None
 except: return None

def _safe_str(v):
 if v is None: return ''
 try:
  if pd.isna(v): return ''
 except: pass
 return str(v).strip()

def rsi(s,n=14):
 d=s.diff(); up=d.clip(lower=0).ewm(alpha=1/n,adjust=False,min_periods=n).mean(); dn=(-d.clip(upper=0)).ewm(alpha=1/n,adjust=False,min_periods=n).mean()
 out=100-100/(1+up/dn)
 out=out.mask((dn==0)&(up>0),100).mask((up==0)&(dn>0),0).mask((up==0)&(dn==0),50)
 return out

def calc(df:pd.DataFrame)->dict:
 d=df.copy().dropna(subset=['Close']); c=d.Close.astype(float); h=d.High.astype(float); l=d.Low.astype(float); o=d.Open.astype(float); v=d.Volume.fillna(0).astype(float)
 x={}; x['close']=c.iloc[-1]; x['chg1d']=(c.iloc[-1]/c.iloc[-2]-1)*100 if len(c)>1 and c.iloc[-2] else None; x['amount']=c.iloc[-1]*v.iloc[-1]
 for w in (20,60,120,252):
  prior=h.iloc[-w:-1] if len(h)>=2 else h.iloc[:0]; mx=prior.max() if len(prior) else np.nan
  x[f'hi_gap{w}']=(c.iloc[-1]/mx-1)*100 if pd.notna(mx) and mx else None; x[f'is_hi{w}']=bool(h.iloc[-1]>=mx) if pd.notna(mx) else False
 lo=l.tail(252).min(); hi=h.tail(252).max(); x['lo_gap252']=(c.iloc[-1]/lo-1)*100 if lo else None; x['pos52w']=(c.iloc[-1]-lo)/(hi-lo)*100 if hi>lo else 50
 mas={w:c.rolling(w).mean() for w in (5,20,60,120)}
 for w,s in mas.items(): x[f'sma{w}']=s.iloc[-1]; x[f'above_ma{w}']=bool(c.iloc[-1]>s.iloc[-1]) if pd.notna(s.iloc[-1]) else False
 vals=[mas[w].iloc[-1] for w in (5,20,60,120)]; x['ma_bull']=all(pd.notna(vals)) and vals[0]>vals[1]>vals[2]>vals[3]; x['ma_bear']=all(pd.notna(vals)) and vals[0]<vals[1]<vals[2]<vals[3]; x['ma_above_count']=sum(x[f'above_ma{w}'] for w in (5,20,60,120))
 x['dist_ma20']=(c.iloc[-1]/mas[20].iloc[-1]-1)*100 if pd.notna(mas[20].iloc[-1]) else None; x['dist_ma60']=(c.iloc[-1]/mas[60].iloc[-1]-1)*100 if pd.notna(mas[60].iloc[-1]) else None; x['ma20_slope']=(mas[20].iloc[-1]/mas[20].iloc[-6]-1)*100 if len(c)>=26 and mas[20].iloc[-6] else None
 x['golden_5_20']=bool(len(c)>=22 and mas[5].iloc[-1]>mas[20].iloc[-1] and mas[5].iloc[-2]<=mas[20].iloc[-2])
 for w in (20,60):
  base=v.iloc[-w:-1].mean(); x[f'vol_ratio{w}']=v.iloc[-1]/base if base else None
 x['vol_burst']=v.tail(5).mean()/v.tail(60).mean() if v.tail(60).mean() else None
 obv=(np.sign(c.diff()).fillna(0)*v).cumsum(); omin,omax=obv.tail(252).min(),obv.tail(252).max(); x['obv_pos']=(obv.iloc[-1]-omin)/(omax-omin)*100 if omax>omin else 50; x['obv_high']=bool(obv.iloc[-1]>=obv.iloc[-252:-1].max()) if len(obv)>1 else False
 x['obv_div']=bool(len(c)>=21 and c.iloc[-1]<c.iloc[-20] and obv.iloc[-1]>obv.iloc[-20])
 for w in (5,20,60,120): x[f'ret{w}']=(c.iloc[-1]/c.iloc[-1-w]-1)*100 if len(c)>w and c.iloc[-1-w] else None
 x['rsi14']=rsi(c).iloc[-1]; streak=0
 for i in range(len(d)-1,-1,-1):
  if c.iloc[i]>o.iloc[i]: streak+=1
  else: break
 x['green_streak']=streak
 mid=c.rolling(150).mean(); sd=c.rolling(150).std(ddof=0); upper=mid+1.5*sd; lower=mid-1.5*sd; x['bb_upper']=upper.iloc[-1]; x['bb_gap']=(c.iloc[-1]/upper.iloc[-1]-1)*100 if pd.notna(upper.iloc[-1]) else None; x['bb_pctb']=(c.iloc[-1]-lower.iloc[-1])/(upper.iloc[-1]-lower.iloc[-1])*100 if pd.notna(upper.iloc[-1]) and upper.iloc[-1]>lower.iloc[-1] else None; x['bb_width']=(upper.iloc[-1]-lower.iloc[-1])/mid.iloc[-1]*100 if pd.notna(mid.iloc[-1]) and mid.iloc[-1] else None
 pc=c.shift(); tr=pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1); atr=tr.rolling(20).mean(); x['atr20']=atr.iloc[-1]/c.iloc[-1]*100 if pd.notna(atr.iloc[-1]) else None
 return {k:(_finite(val) if not isinstance(val,(bool,str)) else val) for k,val in x.items()}

def load_json(p):
 try: return json.loads(Path(p).read_text(encoding='utf-8'))
 except: return {}


KRX_BASE='https://data-dbg.krx.co.kr/svc/apis/sto'
KRX_ENDPOINTS={'KOSPI':'stk_bydd_trd','KOSDAQ':'ksq_bydd_trd'}
KRX_CACHE=Path('cache/kr_ohlcv.csv.gz')

def _numstr(v):
 s=_safe_str(v).replace(',','')
 try: return float(s) if s else np.nan
 except: return np.nan

def krx_get_day(day):
 key=os.environ.get('KRX_API_KEY','').strip()
 if not key: raise RuntimeError('KRX_API_KEY is missing')
 frames=[]; bas=pd.Timestamp(day).strftime('%Y%m%d')
 for market,api_id in KRX_ENDPOINTS.items():
  r=requests.get(f'{KRX_BASE}/{api_id}',headers={'AUTH_KEY':key},params={'basDd':bas},timeout=30)
  if r.status_code!=200: raise RuntimeError(f'KRX {market} {bas}: HTTP {r.status_code}: {r.text[:300]}')
  js=r.json(); rows=js.get('OutBlock_1') or []
  if not isinstance(rows,list): raise RuntimeError(f'KRX {market} {bas}: unexpected response')
  if rows:
   z=pd.DataFrame(rows); z['Market']=market; frames.append(z)
 return pd.concat(frames,ignore_index=True) if frames else pd.DataFrame()

def normalize_krx(z):
 if z.empty: return pd.DataFrame(columns=['Date','Code','Name','Market','Open','High','Low','Close','Volume','Amount','MarketCap'])
 out=pd.DataFrame({
  'Date':pd.to_datetime(z['BAS_DD'],format='%Y%m%d',errors='coerce'),
  'Code':z['ISU_CD'].map(_safe_str),'Name':z['ISU_NM'].map(_safe_str),'Market':z['Market'].map(_safe_str),
  'Open':z['TDD_OPNPRC'].map(_numstr),'High':z['TDD_HGPRC'].map(_numstr),'Low':z['TDD_LWPRC'].map(_numstr),
  'Close':z['TDD_CLSPRC'].map(_numstr),'Volume':z['ACC_TRDVOL'].map(_numstr),
  'Amount':z['ACC_TRDVAL'].map(_numstr),'MarketCap':z['MKTCAP'].map(_numstr)})
 for c in ['Open','High','Low','Close','Volume','Amount','MarketCap']:
  out[c]=pd.to_numeric(out[c],errors='coerce')
 return out.dropna(subset=['Date','Code','Close'])

def _save_krx_cache(cache, new_frames=None):
 frames=[cache] if isinstance(cache,pd.DataFrame) and len(cache) else []
 if new_frames: frames.extend([x for x in new_frames if isinstance(x,pd.DataFrame) and len(x)])
 if not frames: return pd.DataFrame()
 out=pd.concat(frames,ignore_index=True)
 out['Date']=pd.to_datetime(out['Date'],errors='coerce')
 out['Code']=out['Code'].astype(str).str.replace(r'\.0$','',regex=True).str.zfill(6)
 for c in ['Open','High','Low','Close','Volume','Amount','MarketCap']:
  if c in out: out[c]=pd.to_numeric(out[c],errors='coerce')
 out=out.dropna(subset=['Date','Code','Close']).drop_duplicates(['Date','Code'],keep='last').sort_values(['Date','Code'])
 KRX_CACHE.parent.mkdir(parents=True,exist_ok=True)
 tmp=KRX_CACHE.with_suffix('.tmp.gz')
 out.to_csv(tmp,index=False,compression='gzip')
 tmp.replace(KRX_CACHE)
 return out

def update_krx_cache(bootstrap_days=430, checkpoint_every=10):
 KRX_CACHE.parent.mkdir(parents=True,exist_ok=True)
 if KRX_CACHE.exists():
  cache=pd.read_csv(KRX_CACHE,compression='gzip',dtype={'Code':str},parse_dates=['Date'])
  cache=_save_krx_cache(cache)
  start=cache.Date.max().normalize()+pd.Timedelta(days=1) if len(cache) else pd.Timestamp.today().normalize()-pd.Timedelta(days=bootstrap_days)
 else:
  cache=pd.DataFrame(); start=pd.Timestamp.today().normalize()-pd.Timedelta(days=bootstrap_days)
 end=pd.Timestamp.today().normalize(); days=pd.date_range(start,end,freq='B')
 print(f'KRX cache {len(cache):,} rows; checking {len(days)} weekdays')
 pending=[]; success_days=0
 try:
  for i,day in enumerate(days,1):
   try:
    z=normalize_krx(krx_get_day(day))
    if len(z):
     pending.append(z); success_days+=1
     print(f'KRX {day.date()} {len(z):,} rows ({i}/{len(days)})')
     if success_days % checkpoint_every == 0:
      cache=_save_krx_cache(cache,pending); pending=[]
      print(f'KRX checkpoint saved: {len(cache):,} rows through {cache.Date.max().date()}')
   except Exception as e:
    msg=str(e)
    if any(x in msg for x in ('HTTP 401','HTTP 403','Unauthorized','KRX_API_KEY')): raise
    print('KRX warning:',msg)
 finally:
  # Preserve every successful API response even if a later calculation/run fails.
  if pending:
   cache=_save_krx_cache(cache,pending)
   print(f'KRX final checkpoint saved: {len(cache):,} rows through {cache.Date.max().date()}')
 if cache.empty: raise RuntimeError('KRX cache is empty; check API approvals/key')
 return cache

def build_kr():
 cache=update_krx_cache(); sector_map=load_json(OUT/'sector_map_kr.json'); consensus=load_json(OUT/'consensus_kr.json')
 latest=cache.Date.max(); cur=cache.loc[cache.Date==latest].copy()
 bad=cur.Name.astype(str).str.contains(r'스팩|리츠|REIT',case=False,regex=True)|cur.Name.astype(str).str.endswith(('우','우B','우C'))
 cur=cur.loc[~bad]; rows=[]; series={}; dates=[]
 for _,rec in cur.iterrows():
  sym=str(rec.Code).zfill(6); hist=cache.loc[cache.Code.astype(str).str.zfill(6)==sym].sort_values('Date').tail(320)
  if len(hist)<25: continue
  d=hist.set_index('Date')[['Open','High','Low','Close','Volume']].copy()
  d=d.apply(pd.to_numeric,errors='coerce').dropna(subset=['Open','High','Low','Close','Volume'])
  if len(d)<25: continue
  m=calc(d)
  m['amount']=_finite(rec.Amount); m['market_cap']=_finite(rec.MarketCap)
  if (m.get('amount') or 0)<100_000_000: continue
  meta=sector_map.get(sym,{}) if isinstance(sector_map,dict) else {}; con=consensus.get(sym,{}) if isinstance(consensus,dict) else {}
  m.update({'symbol':sym,'name':_safe_str(rec.Name) or sym,'sector':_safe_str(meta.get('sector') if isinstance(meta,dict) else meta) or '미분류'})
  eps=_finite(con.get('eps')); bps=_finite(con.get('bps')); feps=_finite(con.get('forward_eps') or con.get('cns_eps')); div=_finite(con.get('dvr'))
  m['per']=m['close']/eps if eps and eps>0 else None; m['pbr']=m['close']/bps if bps and bps>0 else None
  m['roe']=eps/bps*100 if eps is not None and bps else None; m['div_yield']=div; m['forward_eps']=feps
  m['forward_per']=m['close']/feps if feps and feps>0 else None; m['eps_growth']=(feps/eps-1)*100 if eps and feps else None
  m['sector_per_rel']=None; m['sector_pbr_rel']=None
  if eps and eps>0:
   ps=d.Close.astype(float).tail(252)/eps; mn,mx=ps.min(),ps.max()
   m['per_band_pos']=(m['per']-mn)/(mx-mn)*100 if mx>mn else 50
  else: m['per_band_pos']=None
  rows.append(m); series[sym]=pack_series(d); dates.append(d.index[-1])
 rdf=pd.DataFrame(rows)
 if len(rdf):
  for fld,outkey in [('per','sector_per_rel'),('pbr','sector_pbr_rel')]:
   med=rdf.assign(_v=pd.to_numeric(rdf[fld],errors='coerce')).groupby('sector')['_v'].median().to_dict()
   for r in rows:
    mm=_finite(med.get(r['sector'])); vv=_finite(r.get(fld)); r[outkey]=vv/mm if vv is not None and mm else None
 date=max(dates).strftime('%Y-%m-%d') if dates else latest.strftime('%Y-%m-%d')
 payload={'region':'kr','date':date,'run_at':datetime.now(timezone.utc).isoformat(),'schema':SCHEMA,'rows':rows}
 (OUT/'universe_kr.json').write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
 (OUT/'series_kr.json').write_text(json.dumps({'region':'kr','date':date,'dates':series_calendar(cache.set_index('Date')),'series':series},ensure_ascii=False,separators=(',',':')),encoding='utf-8')
 print('wrote kr',len(rows),'date',date)

def yahoo_quotes(symbols):
 s=requests.Session(); s.headers['User-Agent']=UA
 try:
  s.get('https://fc.yahoo.com',timeout=20); crumb=s.get('https://query2.finance.yahoo.com/v1/test/getcrumb',timeout=20).text.strip()
 except Exception as e: print('Yahoo crumb failed:',e); return {}
 out={}
 for i in range(0,len(symbols),50):
  batch=symbols[i:i+50]
  try:
   r=s.get('https://query2.finance.yahoo.com/v7/finance/quote',params={'symbols':','.join(batch),'crumb':crumb},timeout=30); r.raise_for_status()
   for q in r.json().get('quoteResponse',{}).get('result',[]): out[_safe_str(q.get('symbol'))]=q
  except Exception as e: print('Yahoo batch failed:',i,e)
 return out

def listing(market):
 if fdr is None: raise RuntimeError('FinanceDataReader is required for data collection')
 return fdr.StockListing(market)

def kr_symbols():
 frames=[]
 for m in ('KOSPI','KOSDAQ'):
  try: frames.append(listing(m))
  except Exception as e: print('listing',m,e)
 if not frames: return pd.DataFrame()
 d=pd.concat(frames,ignore_index=True).drop_duplicates('Code')
 name=d.get('Name',pd.Series('',index=d.index)).astype(str)
 bad=name.str.contains(r'스팩|리츠|REIT',case=False,regex=True) | name.str.endswith(('우','우B','우C'))
 return d.loc[~bad].copy()

def us_symbols():
 frames=[]
 for m in ('S&P500','NASDAQ'):
  try: frames.append(listing(m))
  except Exception as e: print('listing',m,e)
 if not frames: return pd.DataFrame()
 d=pd.concat(frames,ignore_index=True)
 col='Symbol' if 'Symbol' in d else 'Code'; d=d.drop_duplicates(col).rename(columns={col:'Symbol'})
 return d

def fetch_history(sym,start):
 if fdr is None: raise RuntimeError('FinanceDataReader is required for data collection')
 for tries in range(3):
  try:
   d=fdr.DataReader(sym,start); 
   if len(d)>=25: return d
  except Exception as e:
   if tries==2: print('history failed',sym,e)
   time.sleep(1+tries)
 return None

def pack_series(df):
 d=df.tail(250).copy()
 for c in ('Open','High','Low','Close','Volume'):
  d[c]=pd.to_numeric(d[c],errors='coerce')
 d[['Open','High','Low','Close']]=d[['Open','High','Low','Close']].replace([np.inf,-np.inf],np.nan)
 d['Close']=d['Close'].ffill().bfill()
 for c in ('Open','High','Low'):
  d[c]=d[c].fillna(d['Close'])
 d['Volume']=d['Volume'].replace([np.inf,-np.inf],np.nan).fillna(0)
 if d['Close'].isna().any(): raise ValueError('series has no finite Close values')
 close=np.rint(d.Close).astype('int64').tolist(); vol=np.rint(d.Volume/1000).astype('int64').tolist()
 tail=d.tail(150); tc=np.rint(tail.Close).astype('int64'); delta=lambda x: (np.rint(x).astype('int64')-tc).tolist()
 return {'c':close,'v':vol,'n':len(d)-len(tail),'o':delta(tail.Open),'h':delta(tail.High),'l':delta(tail.Low)}

def series_calendar(df):
 return [pd.Timestamp(x).strftime('%Y-%m-%d') for x in sorted(pd.Index(df.index).unique())[-250:]]

def build_us():
 region='us'
 start=(pd.Timestamp.today()-pd.Timedelta(days=430)).strftime('%Y-%m-%d'); rows=[]; series={}; dates=[]; calendar_dates=set()
 sector_map=load_json(OUT/'sector_map_kr.json') if region=='kr' else {}; consensus=load_json(OUT/'consensus_kr.json') if region=='kr' else {}
 universe=kr_symbols() if region=='kr' else us_symbols(); symcol='Code' if region=='kr' else 'Symbol'; symbols=[_safe_str(x) for x in universe[symcol].tolist() if _safe_str(x)]
 yq=yahoo_quotes(symbols) if region=='us' else {}
 for idx,sym in enumerate(symbols):
  d=fetch_history(sym,start)
  if d is None: continue
  d=d.copy()
  for c in ('Open','High','Low','Close','Volume'):
   if c in d: d[c]=pd.to_numeric(d[c],errors='coerce')
  d=d.replace([np.inf,-np.inf],np.nan).dropna(subset=['Close'])
  if len(d)<25: continue
  dates.append(pd.Timestamp(d.index[-1])); m=calc(d)
  if (m.get('amount') or 0) < (100_000_000 if region=='kr' else 1_000_000): continue
  rec=universe.loc[universe[symcol].astype(str)==sym].iloc[0].to_dict(); name=_safe_str(rec.get('Name') or rec.get('Security') or sym); m.update({'symbol':sym,'name':name})
  if region=='kr':
   meta=sector_map.get(sym,{}) if isinstance(sector_map,dict) else {}; con=consensus.get(sym,{}) if isinstance(consensus,dict) else {}; m['sector']=_safe_str(meta.get('sector') if isinstance(meta,dict) else meta) or '미분류'
   eps=_finite(con.get('eps')); bps=_finite(con.get('bps')); feps=_finite(con.get('forward_eps') or con.get('cns_eps')); div=_finite(con.get('dvr')); m['per']=m['close']/eps if eps and eps>0 else None; m['pbr']=m['close']/bps if bps and bps>0 else None; m['roe']=eps/bps*100 if eps is not None and bps else None; m['div_yield']=div; m['forward_eps']=feps; m['forward_per']=m['close']/feps if feps and feps>0 else None; m['eps_growth']=(feps/eps-1)*100 if eps and feps else None
   mc=_finite(rec.get('Marcap') or rec.get('MarketCap')); m['market_cap']=mc
  else:
   q=yq.get(sym,{}); m['sector']=_safe_str(rec.get('Sector')) or _safe_str(rec.get('Industry')) or 'Unclassified'; m['market_cap']=_finite(q.get('marketCap') or rec.get('MarketCap')); m['per']=_finite(q.get('trailingPE')); m['forward_per']=_finite(q.get('forwardPE')); m['pbr']=_finite(q.get('priceToBook')); eps=_finite(q.get('epsTrailingTwelveMonths')); feps=_finite(q.get('epsForward')); bps=_finite(q.get('bookValue')); m['forward_eps']=feps; m['roe']=eps/bps*100 if eps is not None and bps else None; dy=_finite(q.get('dividendYield')); m['div_yield']=dy*100 if dy is not None and dy<=1 else dy; m['eps_growth']=(feps/eps-1)*100 if eps and feps else None
  m['sector_per_rel']=None; m['sector_pbr_rel']=None
  # 52-week PER band position: with a stable trailing EPS, PER band position equals price position over the same window.
  trail_eps = eps if 'eps' in locals() else None
  if trail_eps and trail_eps > 0:
   per_s = d.Close.astype(float).tail(252) / trail_eps
   pmin,pmax = per_s.min(),per_s.max(); m['per_band_pos']=(m['per']-pmin)/(pmax-pmin)*100 if m.get('per') is not None and pmax>pmin else 50
  else: m['per_band_pos']=None
  rows.append(m); series[sym]=pack_series(d); calendar_dates.update(pd.Timestamp(x).strftime('%Y-%m-%d') for x in d.tail(250).index)
  if idx%100==0: print(region,idx,'/',len(symbols),'kept',len(rows))
 # sector relative valuation
 rdf=pd.DataFrame(rows)
 if len(rdf):
  for field,outkey in [('per','sector_per_rel'),('pbr','sector_pbr_rel')]:
   med=rdf.assign(_v=pd.to_numeric(rdf[field],errors='coerce')).groupby('sector')['_v'].median().to_dict()
   for r in rows:
    mm=_finite(med.get(r['sector'])); vv=_finite(r.get(field)); r[outkey]=vv/mm if vv is not None and mm else None
 date=max(dates).strftime('%Y-%m-%d') if dates else None; payload={'region':region,'date':date,'run_at':datetime.now(timezone.utc).isoformat(),'schema':SCHEMA,'rows':rows}
 (OUT/f'universe_{region}.json').write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8'); (OUT/f'series_{region}.json').write_text(json.dumps({'region':region,'date':date,'dates':sorted(calendar_dates)[-250:],'series':series},ensure_ascii=False,separators=(',',':')),encoding='utf-8')
 print('wrote',region,len(rows),'date',date)

def self_test():
 idx=pd.date_range('2025-01-01',periods=300,freq='B'); c=pd.Series(np.linspace(100,200,300),index=idx); d=pd.DataFrame({'Open':c-1,'High':c+1,'Low':c-2,'Close':c,'Volume':1000},index=idx); d.iloc[-1,d.columns.get_loc('High')]=999
 x=calc(d); assert x['is_hi20'] is True; assert x['sma5'] > x['sma20'] > x['sma60'] > x['sma120']; assert round(rsi(pd.Series(range(1,40))).iloc[-1])==100
 down=pd.Series(range(40,1,-1)); assert round(rsi(down).iloc[-1])==0
 assert _safe_str(np.nan)=='' and _safe_str(None)=='' and _safe_str(1.2)=='1.2'; assert len(pack_series(d)['c'])==250 and 'd' not in pack_series(d)
 bad=d.copy(); bad.iloc[-1,bad.columns.get_loc('Open')]=np.nan; bad.iloc[-2,bad.columns.get_loc('High')]=np.inf; bad.iloc[-3,bad.columns.get_loc('Volume')]=np.nan; assert len(pack_series(bad)['c'])==250
 print('self_test: OK')

if __name__=='__main__':
 ap=argparse.ArgumentParser(); ap.add_argument('--region',choices=['kr','us','all'],default='all'); ap.add_argument('--self-test',action='store_true'); a=ap.parse_args(); self_test()
 if not a.self_test:
  if a.region in ('kr','all'): build_kr()
  if a.region in ('us','all'): build_us()
