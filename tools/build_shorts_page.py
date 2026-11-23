"""Build the Breakdown Shorts artifact page from portfolio/cohorts/short_*.json.

Usage: python tools/build_shorts_page.py <repo_dir> <current_page.html> <out.html>
The current page supplies the CSS and methodology block; all numbers come from the cohort files.
"""
import json, glob, sys, re, datetime as dt, html
repo, tmpl_path, out = sys.argv[1], sys.argv[2], sys.argv[3]
tmpl = open(tmpl_path).read()
style = re.search(r'(<link rel="stylesheet".*?</style>)', tmpl, re.S).group(1)
meth = re.search(r'(<div class="methodology">.*?</div>\s*</div>\s*</div>)', tmpl, re.S).group(1)
cs = []
for f in sorted(glob.glob(f'{repo}/portfolio/cohorts/short_*.json')):
    d = json.load(open(f))
    if not d.get('snapshots'): continue
    cs.append(d)
W0 = dt.date(2026,8,24)
def wk(cid): return (dt.date.fromisoformat(cid)-W0).days//7+1
def money(x, sign=True):
    s = f"${abs(x):,.0f}"
    return (("+" if x>=0 else "−")+s) if sign else s
def pct(x): return ("+" if x>=0 else "−")+f"{abs(x):.2f}%"
def cls(x): return "win" if x>=0 else "loss"
rows=[]; tick={}
snapdate = max(c['snapshots'][-1]['date'] for c in cs)
latest = max(cs, key=lambda c:c['cohort_id'])
for c in cs:
    s=c['snapshots'][-1]; n=sum(p['notional'] for p in c['positions'])
    pnl=s['portfolio_value']-n; spy=n*s['spy_value']/100; vti=n*s['vti_value']/100
    rows.append(dict(id=c['cohort_id'],n=n,pnl=pnl,ret=s['portfolio_return_pct'],alpha=s['alpha'],spy=spy,vti=vti,c=c,live=c is latest))
    for p in c['positions']:
        sp=s['positions'].get(p['ticker'],{}); v=sp.get('value',p['notional'])
        t=tick.setdefault(p['ticker'],dict(name=p.get('name',''),n=0,pnl=0,k=0))
        t['n']+=p['notional']; t['pnl']+=v-p['notional']; t['k']+=1
closed=[r for r in rows if not r['live']]
allr=rows
N=sum(r['n'] for r in allr); P=sum(r['pnl'] for r in allr); S=sum(r['spy'] for r in allr); V=sum(r['vti'] for r in allr)
wins=sum(1 for r in closed if r['pnl']>=0)
week_now=wk(latest['cohort_id'])
# cohort table
rs=sorted(rows,key=lambda r:-r['pnl'])
tb=[]; be=False
for r in rs:
    if r['pnl']<0 and not be:
        tb.append('<tr class="sub-row"><td colspan="5" style="text-align:center;color:var(--muted);font-style:italic;font-family:\'DM Sans\',sans-serif">— break-even —</td></tr>'); be=True
    tag=' <span class="pill gold">new</span>' if r['live'] else ''
    tb.append(f'<tr><td>{r["id"]}{tag}</td><td>{money(r["n"],False)}</td><td class="{cls(r["pnl"])} fw500">{money(r["pnl"])}</td><td class="{cls(r["ret"])}">{pct(r["ret"])}</td><td class="{cls(r["alpha"])}">{pct(r["alpha"])}</td></tr>')
tb.append(f'<tr class="total-row"><td colspan="2">Total ({len(rows)} short cohorts)</td><td class="{cls(P)}">{money(P)}</td><td class="{cls(P)}">{pct(100*P/N)} blended</td><td class="{cls(P-S)}">{pct(100*(P-S)/N)} alpha</td></tr>')
# ticker table
ts=sorted(tick.items(),key=lambda kv:-kv[1]['pnl']); tt=[]; be=False
for k,t in ts:
    if t['pnl']<0 and not be:
        tt.append('<tr class="sub-row"><td colspan="4" style="text-align:center;color:var(--muted);font-style:italic;font-family:\'DM Sans\',sans-serif">— break-even —</td></tr>'); be=True
    r=100*t['pnl']/t['n']
    tt.append(f'<tr><td><div class="ticker-cell"><span class="ticker-sym">{k}</span><span class="ticker-name">{html.escape(t["name"])}</span></div></td><td class="neutral">{"×"+str(t["k"]) if t["k"]>1 else "—"}</td><td class="{cls(t["pnl"])} fw500">{money(t["pnl"])}</td><td class="{cls(r)}">{pct(r)}</td></tr>')
TP=sum(t['pnl'] for t in tick.values())
tt.append(f'<tr class="total-row"><td colspan="2">Total ({len(tick)} tickers, {len(rows)} cohorts)</td><td class="{cls(TP)}">{money(TP)}</td><td>—</td></tr>')
multi=[k for k,t in tick.items() if t['k']>1]
# cohort detail
def cur(t): return "€" if t.endswith('.BR') else "$"
def detail(c, title, pill, rng):
    s=c['snapshots'][-1]; body=[]
    for p in c['positions']:
        sp=s['positions'].get(p['ticker'],{}); v=sp.get('value',p['notional']); pl=v-p['notional']; pp=sp.get('pnl_pct',0.0)
        body.append(f'<tr><td><div class="ticker-cell"><span class="ticker-sym">{p["ticker"]}</span><span class="ticker-name">{html.escape(p.get("name",""))}</span></div></td><td>{cur(p["ticker"])}{p["entry_price"]:,.2f}</td><td>{cur(p["ticker"])}{sp.get("current_price",p["entry_price"]):,.2f}</td><td>{p["shares"]:,.1f}</td><td class="neutral">{p.get("score",0):.3f}</td><td class="{cls(pl)} fw500">{money(pl)}</td><td class="{cls(pp)}">{pct(pp)}</td></tr>')
    n=sum(p['notional'] for p in c['positions']); pl=s['portfolio_value']-n
    body.append(f'<tr class="total-row"><td colspan="5">Total Short · {money(n,False)}</td><td class="{cls(pl)}">{money(pl)}</td><td class="{cls(pl)}">{pct(s["portfolio_return_pct"])}</td></tr>')
    return f'''<div class="open-section"><div class="section-hdr"><div class="section-title">{title}</div>{pill}<span style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--muted)">{rng}</span></div>
<div class="tbl-wrap"><table class="tbl"><thead><tr><th class="left">Ticker</th><th>Entry</th><th>Current</th><th>Shares</th><th>Score</th><th>P&amp;L $</th><th>P&amp;L %</th></tr></thead><tbody>{"".join(body)}</tbody></table></div>
<div class="note">SPY entry ${c["spy_entry"]:.2f} · VTI entry ${c["vti_entry"]:.2f}</div></div>'''
prev = sorted(cs,key=lambda c:c['cohort_id'])[-2]
pr = prev['snapshots'][-1]['portfolio_return_pct']
sec = detail(prev, f"Week {wk(prev['cohort_id'])} — {prev['cohort_id']} Cohort", f'<span class="pill {"pos" if pr>=0 else "neg"}">{pct(pr)}</span>', f"{prev['cohort_id']} → {snapdate}")
sec += detail(latest, f"Week {week_now} — Open Positions", '<span class="pill gold">In Progress</span>', f"{latest['cohort_id']} → {(dt.date.fromisoformat(latest['cohort_id'])+dt.timedelta(7))}")
states={}; tips={}
for r in rows:
    w=wk(r['id']); states[w]='current' if r['live'] else cls(r['pnl'])
    tips[w]=f"Wk {w}: Cohort {r['id']} " + ("just opened" if r['live'] else f"now {pct(r['ret'])} cumulative")
for w in range(1,week_now):
    if w not in states: tips[w]=f"Wk {w}: no short cohort"
worst=sorted(tick.items(),key=lambda kv:kv[1]['pnl'])[:3]
best=sorted(tick.items(),key=lambda kv:-kv[1]['pnl'])[:2]
notetxt=(f"{wins} of {len(closed)} live cohorts are positive. Biggest drags: " + ", ".join(f"{k} ({money(t['pnl'])})" for k,t in worst) +
         ". Best: " + ", ".join(f"{k} ({money(t['pnl'])})" for k,t in best) + ".")
prices_as_of = dt.date.fromisoformat(snapdate) - dt.timedelta(days=3)
page=f'''<title>Breakdown Shorts</title>
{style}
<div class="page">
<header class="hdr"><div><div class="hdr-eyebrow">Paper Portfolio · Short-Only Breakdown Cohorts</div><div class="hdr-title">Breakdown <span>Shorts</span></div></div>
<div class="hdr-right"><div class="week-badge">Week {week_now} <small>of 52</small></div><div class="hdr-meta">Started 2026-09-07 · Prices as of {prices_as_of:%b %-d} close · Next close {(dt.date.fromisoformat(latest['cohort_id'])+dt.timedelta(7))}</div></div></header>
<div class="cross-link">Long-side cohorts are tracked separately on the <a href="https://claude.ai/artifact/E4z8efhyojccJLLXCV6V9b" target="_blank">Breakout Longs</a> companion artifact — this page is short-only.</div>
<div class="kpi-row">
<div class="kpi {"pos" if P>=0 else "neg"}"><div class="kpi-label">Cumulative Short P&amp;L</div><div class="kpi-value {"pos" if P>=0 else "neg"}-val">{money(P)}</div><div class="kpi-sub">{pct(100*P/N)} on {money(N,False)} across {len(rows)} cohorts</div></div>
<div class="kpi {"pos" if wins*2>=len(closed) else "neg"}"><div class="kpi-label">Win Rate</div><div class="kpi-value {"pos" if wins*2>=len(closed) else "neg"}-val">{wins} / {len(closed)}</div><div class="kpi-sub">{100*wins/len(closed):.0f}% of cohorts positive (excl. new)</div></div>
<div class="kpi spy-card"><div class="kpi-label">SPY Benchmark (dollar-weighted)</div><div class="kpi-value spy-val">{money(S)}</div><div class="kpi-sub">{pct(100*S/N)} · VTI {money(V)} ({pct(100*V/N)})</div></div>
<div class="kpi {"pos" if P-S>=0 else "neg"}"><div class="kpi-label">Alpha vs SPY</div><div class="kpi-value {"pos" if P-S>=0 else "neg"}-val">{money(P-S)}</div><div class="kpi-sub">Short {pct(100*P/N)} vs SPY {pct(100*S/N)}</div></div>
</div>
<div class="note" style="margin:-18px 0 28px">{notetxt}</div>
<div class="weekly-summary"><div class="section-hdr"><div class="section-title">Short Cohorts — Ranked by $ Contribution</div></div>
<div class="tbl-wrap"><table class="tbl"><thead><tr><th class="left">Cohort</th><th>Notional</th><th>$ P&amp;L</th><th>Return</th><th>vs SPY</th></tr></thead><tbody>{"".join(tb)}</tbody></table></div>
<div class="note">Cumulative since each cohort's own entry, from the repo snapshot dated {snapdate} (prices as of the prior Friday close).</div></div>
<div class="weekly-summary"><div class="section-hdr"><div class="section-title">All Short Tickers — Aggregated Across Cohorts</div></div>
<div class="tbl-wrap"><table class="tbl"><thead><tr><th class="left">Ticker</th><th>Cohorts</th><th>$ P&amp;L</th><th>Return %</th></tr></thead><tbody>{"".join(tt)}</tbody></table></div>
<div class="note">×N = held short in N concurrent cohorts ({", ".join(sorted(multi))}). Summed/blended across every cohort holding that ticker.</div></div>
{sec}
<div class="timeline-section"><div class="section-title" style="margin-bottom:10px">52-Week Progress</div><div class="week-grid" id="week-grid"></div></div>
{meth}
</div>
<script>
const weekStates={json.dumps(states)};const weekTips={json.dumps(tips)};
const grid=document.getElementById('week-grid');
for(let i=1;i<=52;i++){{const c=document.createElement('div');c.className='wk-cell '+(weekStates[i]||'future');c.textContent=i;c.title=weekTips[i]||('Week '+i);grid.appendChild(c);}}
</script>'''
open(out,'w').write(page)
print(f"P={P:.0f} N={N:.0f} S={S:.0f} V={V:.0f} alpha={P-S:.0f} wins={wins}/{len(closed)} week={week_now} snap={snapdate}")
