"""고버니 트렌드 레이더 빌드 스크립트.

사용법:
  python3 build.py <데이터> [이름표.json]
    <데이터> : CSV 폴더(종목별 OHLCV CSV) 또는 '#TICKER' 블록 텍스트 파일
    이름표    : {"MU": "마이크론", ...} 형태(선택)
결과: out/radar.html (요약 내장), out/t/<TICKER>.json (종목 상세)
"""
import sys, os, json, glob, re, math
import pandas as pd
from engine import build_all, load as load_blocks

HERE = os.path.dirname(os.path.abspath(__file__))


def load_csv(path):
    raw = pd.read_csv(path, header=None, dtype=str)
    # 헤더 줄 찾기 (Date / Datetime / 날짜 등)
    hdr = None
    for i in range(min(5, len(raw))):
        row = [str(x).strip().lower() for x in raw.iloc[i].tolist()]
        if any(x in ('open', 'high', 'low', 'close') for x in row):
            hdr = i
            break
    if hdr is None:
        raise ValueError('헤더 없음')
    cols = [str(x).strip().lower() for x in raw.iloc[hdr].tolist()]
    body = raw.iloc[hdr + 1:].copy()
    body.columns = cols
    if cols[0] in ('price', 'nan', '') or 'date' not in cols:
        body = body.rename(columns={cols[0]: 'date'})
    if 'date' not in body.columns:
        dc = [c for c in body.columns if 'date' in c or 'time' in c]
        body = body.rename(columns={dc[0]: 'date'})
    body['date'] = pd.to_datetime(body['date'].str.slice(0, 10), errors='coerce')
    body = body.dropna(subset=['date'])
    out = pd.DataFrame({'date': body['date']})
    for k, src in (('o', 'open'), ('h', 'high'), ('l', 'low'), ('c', 'close'), ('v', 'volume')):
        out[k] = pd.to_numeric(body[src], errors='coerce')
    out = out.dropna(subset=['o', 'h', 'l', 'c']).sort_values('date').drop_duplicates('date', keep='last')
    out['v'] = out['v'].fillna(0)
    out = out[out.c > 0]
    return out.tail(400).reset_index(drop=True)


def load_any(src):
    if os.path.isdir(src):
        data = {}
        for p in sorted(glob.glob(os.path.join(src, '*.csv'))):
            sym = os.path.splitext(os.path.basename(p))[0]
            try:
                data[sym] = load_csv(p)
            except Exception as ex:
                print(f'READ FAIL {sym}: {ex}')
        return data
    return load_blocks(src)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'data.txt')
    names = {}
    if len(sys.argv) > 2 and os.path.exists(sys.argv[2]):
        names = json.load(open(sys.argv[2], encoding='utf-8'))
    data = load_any(src)
    # QQQ를 맨 앞에 (상대강도 기준)
    if 'QQQ' in data:
        data = {'QQQ': data['QQQ'], **{k: v for k, v in data.items() if k != 'QQQ'}}
    print(f'loaded {len(data)} tickers')
    res = build_all(data)
    outdir = os.path.join(HERE, 'out'); os.makedirs(os.path.join(outdir, 't'), exist_ok=True)
    for f in glob.glob(os.path.join(outdir, 't', '*.json')):
        os.remove(f)
    summary = []
    for sym, r in res.items():
        if sym.startswith('_'):
            continue
        d, e = r['dash'], r['easy']
        last = r['candles'][-1][0]
        c = d['close']
        r['dp'] = 0 if c >= 10000 else (1 if c >= 1000 else 2)
        r['name'] = names.get(sym, '')
        lastsig = e['signals'][-1] if e['signals'] else None
        summary.append(dict(
            sym=sym, name=names.get(sym, ''), last=last, close=c, chg=d['chg'], dp=r['dp'],
            light=e['light'], why=e['reason'], plan=e['plan'],
            grade=d['grade'], conv=d['conv'], nchk=d['nchk'], rs=d['rs'], state=d['state'],
            today=[s['name'] for s in e['signals'] if s['t'] == last],
            todayK=[s['k'] for s in e['signals'] if s['t'] == last],
            lastSig=None if not lastsig else dict(t=lastsig['t'], k=lastsig['k'], name=lastsig['name']),
            yes=sum(1 for x in e['checks'] if x[1]),
            up10=r['prob']['up'], dn10=r['prob']['dn']))
        fid = sym if re.match(r'^[A-Za-z0-9._-]+$', sym) else 'u' + sym.encode('utf-8').hex()
        summary[-1]['file'] = fid
        with open(os.path.join(outdir, 't', f'{fid}.json'), 'w', encoding='utf-8') as fh:
            json.dump(r, fh, ensure_ascii=False, separators=(',', ':'))
    from collections import Counter
    asof = Counter(s['last'] for s in summary).most_common(1)[0][0]
    idx = dict(asof=asof, summary=summary, _stats=res['_stats'], _base=res['_base'])
    tpl = open(os.path.join(HERE, 'template.html'), encoding='utf-8').read()
    html = tpl.replace('/*DATA*/', json.dumps(idx, ensure_ascii=False, separators=(',', ':')))
    open(os.path.join(outdir, 'radar.html'), 'w', encoding='utf-8').write(html)
    lights = {}
    for s in summary:
        lights[s['light']] = lights.get(s['light'], 0) + 1
    print(f'OK n={len(summary)} asof={asof} lights={lights} html={len(html)//1024}KB')


if __name__ == '__main__':
    main()
