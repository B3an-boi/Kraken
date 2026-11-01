'use strict';
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=v=>v==null?'—':'$'+(Math.abs(v)>=1e6?(v/1e6).toFixed(2)+'M':Math.abs(v)>=1e3?(v/1e3).toFixed(1)+'K':Number(v).toFixed(0));
const pct=(v,d=0)=>v==null?'—':(v*100).toFixed(d)+'%';
const spct=(v,d=1)=>v==null?'—':(v>=0?'+':'')+(v*100).toFixed(d)+'%';
const ago=ts=>{if(!ts)return 'never';const s=Date.now()/1000-ts;return s<60?Math.round(s)+'s ago':s<3600?Math.round(s/60)+'m ago':s<86400?(s/3600).toFixed(1)+'h ago':Math.round(s/86400)+'d ago'};
const hhmm=ts=>new Date(ts*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
const fdur=m=>m>=60?(m/60).toFixed(m>=600?0:1)+'h':Math.round(m)+'m';
const ST={status:null,settings:null,view:'hunter'};

function toast(msg,err){const d=document.createElement('div');d.textContent=msg;if(err)d.className='err';$('#toast').appendChild(d);setTimeout(()=>d.remove(),err?6000:3200)}
async function api(path,opt={}){
  const r=await fetch(path,{headers:{'Content-Type':'application/json'},...opt,body:opt.body?JSON.stringify(opt.body):undefined});
  let j=null;try{j=await r.json()}catch(e){}
  if(!r.ok)throw new Error((j&&(typeof j.detail==='string'?j.detail:JSON.stringify(j.detail)))||('HTTP '+r.status));
  return j;
}
function confirmDlg(title,body,yes){
  return new Promise(res=>{const d=$('#dlg');$('#dlgT').textContent=title;$('#dlgB').innerHTML=body;$('#dlgYes').textContent=yes||'Confirm';
    $('#dlgYes').onclick=()=>{d.close();res(true)};$('#dlgNo').onclick=()=>{d.close();res(false)};d.showModal();});
}
const tokLink=(a,sym)=>`<div class="tok"><b>${esc(sym)}</b><a href="https://gmgn.ai/${esc((ST.settings&&ST.settings.chain)||'sol')}/token/${encodeURIComponent(a)}" target="_blank" rel="noopener noreferrer">${esc(a.slice(0,5))}…${esc(a.slice(-4))} ↗</a></div>`;
const scoreBar=s=>s==null?'—':`<div class="scorebar"><div class="b"><i style="width:${Math.max(0,Math.min(100,s))}%"></i></div><span>${s}</span></div>`;

/* nav */
document.querySelectorAll('#nav button').forEach(b=>b.onclick=()=>show(b.dataset.v));
function show(v){
  ST.view=v;
  document.querySelectorAll('#nav button').forEach(b=>b.classList.toggle('on',b.dataset.v===v));
  document.querySelectorAll('.view').forEach(s=>s.classList.toggle('on',s.id==='v-'+v));
  try{localStorage.setItem('kraken.view',v)}catch(e){}
  refresh();
}

/* status / header */
async function loadStatus(){
  const s=await api('/api/status');ST.status=s;
  $('#ver').textContent='v'+s.version;
  $('#srcPill').className='pill '+(s.live_data?'live':'demo');
  $('#srcTxt').textContent=s.live_data?'GMGN live data':(s.forced_demo?'demo (forced)':'demo data');
  $('#demoBanner').classList.toggle('on',!s.live_data);
  const real=s.mode==='LIVE';
  $('#modeBtn').className='pill modebtn'+(real?' real':'');
  $('#modeTxt').textContent=real?'LIVE · real funds':'SHADOW · paper';
  $('#liveBanner').classList.toggle('on',real);
  $('#posPill').textContent=`${s.positions.open} open · ${s.positions.exposure.toFixed(3)} / ${s.positions.max_exposure}`;
  $('#bPos').textContent=s.positions.open;
  $('#chainSel').value=s.chain;
  if(s.rate_limited_s>0)toast(`GMGN rate limit: pausing ${s.rate_limited_s}s`,true);
}
$('#modeBtn').onclick=async()=>{
  const toLive=!ST.status||ST.status.mode!=='LIVE';
  if(toLive&&!(await confirmDlg('Switch to LIVE trading?','Buy and Sell will send <b>real swaps with real funds</b> from the wallet bound to your GMGN key. Trades are irreversible. Kraken still only trades when you click.','Enable LIVE')))return;
  try{await api('/api/settings',{method:'POST',body:{mode:toLive?'LIVE':'SHADOW'}});toast(toLive?'LIVE trading enabled':'Back to paper trading');}catch(e){toast(e.message,true)}
  await loadStatus();
};
$('#chainSel').onchange=async e=>{try{await api('/api/settings',{method:'POST',body:{chain:e.target.value}});toast('Chain: '+e.target.value.toUpperCase());refresh(true)}catch(err){toast(err.message,true)}};

async function buy(addr,sym,source){
  const live=ST.status&&ST.status.mode==='LIVE',size=ST.settings&&ST.settings.risk.buy_size;
  if(live&&!(await confirmDlg(`Buy ${esc(sym)} for real?`,`Swap <b>${size}</b> native on ${esc((ST.settings.chain||'').toUpperCase())} into ${esc(sym)}. This is irreversible.`,'Buy now')))return;
  try{const p=await api('/api/buy',{method:'POST',body:{address:addr,symbol:sym,source}});toast(`${p.mode==='LIVE'?'Bought':'Paper buy'} ${p.symbol} · ${p.size}`);loadStatus();}
  catch(e){toast(e.message,true)}
}
async function sell(id,sym){
  const p=((ST.pos&&ST.pos.open)||[]).find(x=>x.id===id);
  if(p&&p.mode==='LIVE'&&!(await confirmDlg(`Sell ${esc(sym)}?`,'Sells 100% of this position with a real swap.','Sell now')))return;
  try{const q=await api('/api/sell',{method:'POST',body:{id}});toast(`Closed ${q.symbol} ${spct(q.pnl_pct)}`);loadPositions();loadStatus();}
  catch(e){toast(e.message,true)}
}

/* base hunter */
function sparkSVG(o){
  const pts=o.spark||[];if(pts.length<2)return '<svg></svg>';
  const W=320,H=92,P=6,hs=pts.map(p=>p[1]),ls=pts.map(p=>p[2]);
  const lg=v=>Math.log(Math.max(v,1e-18)),lt=lg(Math.max(...hs)),lb=lg(Math.min(...ls)),span=(lt-lb)||1;
  const y=v=>P+(H-2*P)*(1-(lg(v)-lb)/span),x=i=>P+(W-2*P)*i/(pts.length-1);
  const line=pts.map((p,i)=>`${i?'L':'M'}${x(i).toFixed(1)},${y(p[0]).toFixed(1)}`).join('');
  const b=o.base,windowMin=pts.length*(o.spark_step_min||o.bar_min||5);
  const frac=Math.min(1,b.length/Math.max(windowMin,1));
  const x0=W-P-(W-2*P)*frac,y0=y(b.top),y1=y(b.low);
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Price chart with the base boxed">
    <rect x="${x0.toFixed(1)}" y="${y0.toFixed(1)}" width="${(W-P-x0).toFixed(1)}" height="${Math.max(2,y1-y0).toFixed(1)}" fill="#3ef0c61a" stroke="#3ef0c6" stroke-dasharray="3 3" rx="3"/>
    <path d="${line}" fill="none" stroke="#2bb8ff" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg>`;
}
function hunterCard(o){
  const b=o.base,sup=o.supply||0,mc=v=>money(v*sup),floor='pump_x' in b;
  const net=(o.flow&&o.flow.net_in_base)||0;
  return `<div class="hc">
    <div class="head">${tokLink(o.address,o.symbol)}<div class="score">${o.score}<small>${o.p!=null?'model '+Math.round(o.p*100)+'%':'rule '+o.rule}</small></div></div>
    ${sparkSVG(o)}
    <div class="kv">
      <div>Market cap<b>${money(o.mcap)}</b></div>
      <div>Age<b>${fdur(o.age_min)}</b></div>
      <div>Base<b>${fdur(b.length)} · ±${(b.range*50).toFixed(1)}%</b></div>
      ${floor?`<div>Pump → flush<b>${b.pump_x.toFixed(1)}× → −${pct(b.retrace)}</b></div><div>Vol vs pump<b>${pct(b.vol_decay)}</b></div>`:`<div>Pullback<b>${pct(b.pullback)}</b></div><div>Vol wake<b>${(b.wake||0).toFixed(1)}×</b></div>`}
      <div>Smart $ in base<b class="${net>0?'up':net<0?'down':''}">${net?(net>0?'+':'−')+money(Math.abs(net)):'—'}</b></div>
    </div>
    <div class="row" style="gap:4px"><span class="tag">${esc(o.pattern)}</span>${o.smart?`<span class="tag good">${o.smart} smart</span>`:''}${o.kol?`<span class="tag good">${o.kol} KOL</span>`:''}<span class="tag">at ${pct(b.pos)} of range</span></div>
    <div class="acts">
      <button class="btn primary small" data-buy="${esc(o.address)}" data-sym="${esc(o.symbol)}">Buy</button>
      <span class="sub mono">dip ${sup?mc(b.dip_entry):'—'} · breakout ${sup?mc(b.breakout_entry):'—'}</span>
    </div>
  </div>`;
}
async function loadHunter(){
  const h=await api('/api/hunter');ST.hunter=h;const s=h.stats||{};
  $('#hStatus').innerHTML=(h.scanning?'<span class="spin"></span> scanning · ':'')+`last scan ${ago(h.last_scan)} · smart-money flow ${h.flow.coverage_min}m, ${h.flow.tokens} tokens`+(h.error?` · <span class="down">${esc(h.error)}</span>`:'');
  $('#hFunnel').innerHTML=s.pool!=null?`<span>pool <b>${s.pool}</b></span><i>→</i><span>safe <b>${s.safe}</b></span><i>→</i><span>prefilter <b>${s.prefilter}</b></span><i>→</i><span>charted <b>${s.charted}</b></span><i>→</i><span>bases <b>${s.found}</b></span>`:'';
  $('#hWhy').innerHTML=Object.entries(s.why||{}).map(([k,v])=>`<span class="why">${esc(k)} · ${v}</span>`).join('');
  $('#bHunter').textContent=h.results.length;
  $('#hCards').innerHTML=h.results.length?h.results.map(hunterCard).join(''):`<div class="empty card" style="grid-column:1/-1"><div class="big">🌊</div>${h.last_scan?'No bases right now. The rejection reasons are above; loosen them in Settings → Base Hunter.':'No scan yet. Click <b>Scan now</b>.'}</div>`;
  if(ST.settings){$('#hAuto').checked=ST.settings.hunter.auto;$('#hSetup').value=ST.settings.hunter.setup;}
}
$('#hScan').onclick=async()=>{try{await api('/api/hunter/scan',{method:'POST'});toast('Scanning…');setTimeout(loadHunter,800)}catch(e){toast(e.message,true)}};
$('#hAuto').onchange=e=>saveQuick({hunter:{auto:e.target.checked}});
$('#hSetup').onchange=e=>saveQuick({hunter:{setup:e.target.value}});
$('#hCards').onclick=e=>{const b=e.target.closest('[data-buy]');if(b)buy(b.dataset.buy,b.dataset.sym,'hunter')};

/* screener */
async function loadScreen(){
  const s=await api('/api/screen');ST.screen=s;const f=s.funnel||{};
  $('#sStatus').innerHTML=(s.running?'<span class="spin"></span> running · ':'')+`last run ${ago(s.ts)}`+(s.error?` · <span class="down">${esc(s.error)}</span>`:'');
  $('#sFunnel').innerHTML=f.scanned!=null?`<span>trending <b>${f.scanned}</b></span><i>→</i><span>safe <b>${f.safety}</b></span><i>→</i><span>market &amp; consensus <b>${f.market}</b></span><i>→</i><span>passed <b>${f.passed}</b></span>`:'';
  const rows=(s.results||[]).filter(o=>$('#sRej').checked||o.status!=='rejected');
  $('#bScreen').textContent=f.passed||0;
  $('#sTbl').innerHTML=`<thead><tr><th>Token</th><th class="num">MC</th><th class="num">Liq</th><th class="num">1h</th><th class="num">5m</th><th class="num">Buys</th><th class="num">Smart/KOL</th><th class="num">Top 10</th><th>Score</th><th>Why</th><th></th></tr></thead><tbody>`+
   (rows.length?rows.map(o=>{const t=o.token,rej=o.status==='rejected';return `<tr class="${rej?'dim':''}">
    <td>${tokLink(t.address,t.symbol)}</td><td class="num">${money(t.mcap)}</td><td class="num">${money(t.liquidity)}</td>
    <td class="num ${t.chg_1h>=0?'up':'down'}">${spct(t.chg_1h,0)}</td><td class="num ${t.chg_5m>=0?'up':'down'}">${spct(t.chg_5m,1)}</td>
    <td class="num">${pct(t.buy_ratio)}</td><td class="num">${t.smart}/${t.kol}</td><td class="num">${pct(t.top10)}</td>
    <td>${scoreBar(o.score)}</td><td>${o.reasons.map(r=>`<span class="tag ${rej?'bad':''}">${esc(r)}</span>`).join('')}</td>
    <td>${o.status==='pass'?`<button class="btn small primary" data-buy="${esc(t.address)}" data-sym="${esc(t.symbol)}">Buy</button>`:''}</td></tr>`}).join(''):`<tr><td colspan="11"><div class="empty">${s.ts?'Nothing passed. Loosen the screener in Settings.':'Click <b>Run screen</b> to pull trending tokens.'}</div></td></tr>`)+'</tbody>';
  if(ST.settings)$('#sAuto').checked=ST.settings.screen.auto;
}
$('#sRun').onclick=async()=>{try{await api('/api/screen/run',{method:'POST'});toast('Screening…');setTimeout(loadScreen,800)}catch(e){toast(e.message,true)}};
$('#sAuto').onchange=e=>saveQuick({screen:{auto:e.target.checked}});
$('#sRej').onchange=()=>{try{localStorage.setItem('kraken.rej',$('#sRej').checked?'1':'0')}catch(e){};loadScreen()};
$('#sTbl').onclick=e=>{const b=e.target.closest('[data-buy]');if(b)buy(b.dataset.buy,b.dataset.sym,'screener')};

/* positions */
async function loadPositions(){
  const p=await api('/api/positions');ST.pos=p;const s=p.summary;
  const sg=v=>`<span class="${v>=0?'up':'down'}">${v>=0?'+':''}${v.toFixed(4)}</span>`;
  $('#pTiles').innerHTML=[['Open',`${s.open} / ${s.max_positions}`],['Exposure',`${s.exposure.toFixed(3)} / ${s.max_exposure}`],['Unrealized',sg(s.unrealized)],['Realized 24h',sg(s.realized_24h),`loss limit ${s.daily_loss_limit}`]]
    .map(([k,v,x])=>`<div class="tile"><div class="k">${k}</div><div class="v">${v}</div>${x?`<div class="s">${x}</div>`:''}</div>`).join('');
  $('#pOpen').innerHTML=`<thead><tr><th>Token</th><th>Mode</th><th class="num">Size</th><th class="num">Entry</th><th class="num">Now</th><th class="num">P/L</th><th>Signals</th><th>Opened</th><th></th></tr></thead><tbody>`+
   (p.open.length?p.open.map(x=>`<tr><td>${tokLink(x.address,x.symbol)}</td><td><span class="tag ${x.mode==='LIVE'?'bad':''}">${x.mode}</span></td><td class="num">${x.size}</td>
     <td class="num">${Number(x.entry_price).toPrecision(4)}</td><td class="num">${Number(x.last_price).toPrecision(4)}</td>
     <td class="num ${x.pnl_pct>=0?'up':'down'}">${spct(x.pnl_pct)}</td>
     <td>${(x.signals||[]).map(s=>`<span class="tag warn" title="${esc(s.msg)}">${esc(s.kind.replace('_',' '))}</span>`).join('')||'<span class="sub">—</span>'}</td>
     <td class="sub">${ago(x.entry_ts)}</td><td><button class="btn small danger" data-sell="${esc(x.id)}" data-sym="${esc(x.symbol)}">Sell</button></td></tr>`).join('')
     :`<tr><td colspan="9"><div class="empty"><div class="big">🦑</div>No open positions. Buy from Base Hunter or the Screener.</div></td></tr>`)+'</tbody>';
  $('#pClosed').innerHTML=`<thead><tr><th>Token</th><th>Mode</th><th class="num">Size</th><th class="num">P/L</th><th>Reason</th><th>Closed</th></tr></thead><tbody>`+
   (p.closed.length?p.closed.map(x=>`<tr><td>${tokLink(x.address,x.symbol)}</td><td><span class="tag">${x.mode}</span></td><td class="num">${x.size}</td><td class="num ${x.pnl_pct>=0?'up':'down'}">${spct(x.pnl_pct)} (${x.pnl>=0?'+':''}${x.pnl.toFixed(4)})</td><td class="sub">${esc(x.exit_reason)}</td><td class="sub">${ago(x.exit_ts)}</td></tr>`).join('')
     :`<tr><td colspan="6"><div class="empty">Nothing closed yet.</div></td></tr>`)+'</tbody>';
}
$('#pOpen').onclick=e=>{const b=e.target.closest('[data-sell]');if(b)sell(b.dataset.sell,b.dataset.sym)};

/* learning */
const BT=[['min_score','Min rule score','',1],['max_range','Max base range %','pct',1],['min_base_len','Min base (min)','',5],['min_pump','Min pump ×','',0.5],['min_retrace','Min retrace %','pct',5],['max_vol_ratio','Max vol / pump %','pct',5],['tp','Take profit %','pct',5],['sl','Stop loss %','pct',5]];
$('#btForm').innerHTML=BT.map(([k,l,,st])=>`<div class="f"><label for="bt_${k}">${l}</label><input type="number" step="${st}" id="bt_${k}" placeholder="any"></div>`).join('');
async function loadLearn(){
  const h=await api('/api/hunter');const L=h.learn,m=h.model,lab=h.label;
  $('#lTiles').innerHTML=[['Snapshots',L.samples,`${L.pending} waiting for their ${lab.horizon_min}m outcome`],['Labeled',L.labeled,`win = +${pct(lab.tp)} before −${pct(lab.sl)}`],['Win rate',pct(L.win_rate),`${L.wins} wins`],['Score ≥ 60 wins',pct(L.hi_score_win_rate),`${L.hi_score_n} snapshots`],['Model AUC',m.auc!=null?m.auc.toFixed(2):'—',m.base_auc!=null?`rule score ${m.base_auc.toFixed(2)} · 0.5 = coin flip`:'0.5 = coin flip'],['Model say',Math.round((h.blend||0)*100)+'%','weight in the final score']]
    .map(([k,v,s])=>`<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join('');
  const need=h.min_labeled||40;
  $('#lProg').style.width=Math.min(100,L.labeled/need*100)+'%';
  $('#lProgTxt').textContent=m.ready?`Model trained on ${m.n} outcomes (${m.pos} wins).`:`${L.labeled} / ${need} labeled outcomes. ${m.why||''}`;
  const w=(m.weights||[]).slice(0,10),mx=Math.max(...w.map(x=>Math.abs(x[1])),1e-9);
  $('#lWeights').innerHTML=w.length?'<div class="sub" style="margin-bottom:6px">What the model learned (green raises win odds, red lowers them)</div>'+w.map(([k,v])=>`<div class="br"><span>${esc(k)}</span><span class="t"><i style="width:${Math.abs(v)/mx*100}%;background:${v>0?'var(--glow)':'var(--coral)'}"></i></span><span style="text-align:right">${v>0?'+':''}${v.toFixed(2)}</span></div>`).join(''):'';
  $('#lRecent').innerHTML=`<thead><tr><th>Token</th><th class="num">Score</th><th>Result</th><th class="num">Max up</th><th class="num">Max down</th><th class="num">End</th><th>When</th></tr></thead><tbody>`+
   (h.recent.length?h.recent.map(r=>`<tr><td>${tokLink(r.address,r.symbol)}</td><td class="num">${r.rule??'—'}</td><td><span class="tag ${r.win?'good':'bad'}">${r.win?'WIN':'LOSS'}</span></td><td class="num up">${spct(r.max_up,0)}</td><td class="num down">−${pct(r.max_dd)}</td><td class="num ${r.end_ret>=0?'up':'down'}">${spct(r.end_ret,0)}</td><td class="sub">${ago(r.ts)}</td></tr>`).join('')
    :`<tr><td colspan="7"><div class="empty">Outcomes appear ${lab.horizon_min} minutes after each Base Hunter snapshot. Keep kraken running with auto-scan on.</div></td></tr>`)+'</tbody>';
}
async function runBT(){
  const q=new URLSearchParams();
  BT.forEach(([k,,f])=>{const v=$('#bt_'+k).value;if(v!=='')q.set(k,f==='pct'?(+v/100):+v)});
  try{const b=await api('/api/backtest?'+q);
    $('#btRes').innerHTML=b.n?`<b>${b.n}</b> of ${b.total} snapshots match · win rate <b class="${b.win_rate>=.5?'up':''}">${pct(b.win_rate)}</b> · avg outcome ${spct(b.avg_outcome)}${b.approx?' · <span class="tag warn">approx</span>':''}`:`No labeled snapshots match (${b.total} total).`;
    $('#btBuckets').innerHTML=Object.values(b.buckets).filter(x=>x.rows.length).map(x=>`<div><div class="sub" style="margin-bottom:4px">${esc(x.label)}</div><div class="bars">${x.rows.map(r=>`<div class="br"><span>${esc(r.range)}</span><span class="t"><i style="width:${r.win_rate*100}%"></i></span><span style="text-align:right">${pct(r.win_rate)} · ${r.n}</span></div>`).join('')}</div></div>`).join('');
  }catch(e){toast(e.message,true)}
}
$('#btRun').onclick=runBT;
$('#btClear').onclick=()=>{BT.forEach(([k])=>{$('#bt_'+k).value=''});runBT()};

/* activity */
async function loadActivity(){
  const a=await api('/api/events');
  $('#aLog').innerHTML=a.events.length?a.events.map(e=>`<div><time>${hhmm(e.ts)}</time><span class="kind ${esc(e.kind)}">${esc(e.kind)}</span><span>${esc(e.msg)}</span></div>`).join(''):'<div class="sub">No events yet.</div>';
  $('#aAlerts').innerHTML=a.alerts.length?a.alerts.map(e=>`<div><time>${hhmm(e.ts)}</time><span><b>${esc(e.title)}</b><br><span class="sub">${esc(e.body)}</span><br><span class="sub">${esc(Object.entries(e.result||{}).map(([k,v])=>k+': '+(v===200||v===204?'sent':v)).join(' · '))}</span></span></div>`).join(''):'<div class="sub">No alerts sent yet. Set them up in Settings → Alerts.</div>';
}

/* settings: [key, label, kind, help, step]; kinds: num, int, pct (0-1 shown as %), x (1.x shown as % above), bool, select:a=A|b=B, text, secret */
const SPEC={
 hunter:['Base Hunter',[
  ['setup','Setup','select:floor=Post-pump floor|any=Any tight range','Floor = pump, crash, then flat at the lows. Any = any tight range on 1m candles.'],
  ['auto','Auto-scan','bool','Scans in the background and feeds the learning loop.'],
  ['auto_every_min','Scan every (min)','int','',1],['scan_n','Charts per scan','int','Each chart is 1 GMGN API call.',5],
  ['min_base_min','Min base length (min)','int','How long the flat range must hold.',5],['max_range','Max base range','pct','(top − low) / mid of the base.',1],
  ['min_pump','Min launch pump ×','num','Peak ÷ pre-peak low. The most common rejection.',0.5],['min_retrace','Min retrace','pct','How far the base sits below the peak.',5],
  ['max_vol_ratio','Base vol ≤ % of pump','pct','Volume must have dried up.',5],['near_low','Base ≤ % above the low','x','Base low vs lowest low after the peak.',1],
  ['max_mc_vs_ath','MC ≤ % of ATH','pct','Prefilter: off its highs.',5],['min_usd_per_min_floor','Min $/min in base (floor)','num','Below = dead.',5],
  ['min_usd_per_min_any','Min $/min (any setup)','num','',10],
  ['min_mcap','Min market cap $','num','',1000],['max_mcap','Max market cap $ (0 = any)','num','',10000],
  ['max_age_h','Max age h (0 = any)','num','',1],['min_age_min','Min age (min)','num','',5],['min_liq','Min liquidity $','num','',1000],
  ['max_chg_1h','Max 1h move','pct','Skip coins already moving.',5],['max_chg_5m','Max 5m move','pct','',1],
  ['label_tp','Win = up','pct','Learning label: a win if price rises this much…',5],['label_sl','…before down','pct','…before falling this much…',5],['label_horizon_min','…within (min)','int','',10]]],
 screen:['Screener',[
  ['interval','Trending window','select:1m|5m|1h|6h|24h',''],['limit','Tokens per run','int','',10],
  ['auto','Auto-screen','bool',''],['auto_every_min','Every (min)','int','',1],
  ['min_score','Min score to pass','int','',5],['min_smart_money','Min smart money + KOL','int','',1],
  ['min_liquidity','Min liquidity $','num','',1000],['min_mcap','Min market cap $','num','',1000],['max_mcap','Max market cap $ (0 = any)','num','',100000],
  ['max_top10','Max top-10 holding','pct','',5],['max_dev_hold','Max dev holding','pct','',1],['max_bundler','Max bundled','pct','',5],
  ['max_rug','Max rug ratio','pct','',5],['max_buy_tax','Max buy tax','pct','',1],['max_sell_tax','Max sell tax','pct','',1],
  ['require_renounced','Require renounced mint','bool','Safety gates also apply to Base Hunter.'],['show_rejected','Keep rejected tokens','bool','']]],
 risk:['Trading & risk',[
  ['buy_size','Buy size (native)','num','SOL on Solana, ETH/BNB on EVM chains.',0.01],['slippage','Slippage','pct','',1],
  ['max_positions','Max open positions','int','',1],['max_exposure','Max total exposure','num','',0.1],['daily_loss_limit','Daily loss limit','num','Buying pauses for 24h after this realized loss.',0.1],
  ['stop_loss','Stop-loss signal','pct','Alert when down this much.',5],['take_profit','Take-profit signal','pct','Alert when up this much.',10],
  ['monitor_every_s','Check positions every (s)','int','',5],['exit_on_safety_drop','Safety-drop signal','bool','Alert on a honeypot flag or top-10 holders jumping 15+ points.']]],
 alerts:['Alerts',[
  ['enabled','Alerts on','bool',''],['min_score','Min score to alert','int','',5],
  ['on_floor','Base Hunter finds','bool',''],['on_screen','Screener passes','bool',''],['on_exit','Exit signals','bool',''],
  ['ntfy_topic','ntfy.sh topic','text','Install the ntfy app and subscribe to the same topic. Use a long random name; topics are public.'],
  ['telegram_token','Telegram bot token','secret','From @BotFather.'],['telegram_chat_id','Telegram chat ID','text','Message your bot, then get your ID from @userinfobot.'],
  ['discord_webhook','Discord webhook URL','secret','Server settings → Integrations → Webhooks.']]],
 rate:['GMGN rate limits',[
  ['min_gap_s','Seconds between calls','num','Free tier ≈ 1.2 · Plus ≈ 0.15',0.05],['max_inflight','Parallel calls','int','Free tier 1 · Plus 4',1]]],
};
const toUi=(k,v)=>k==='pct'?+(v*100).toFixed(2):k==='x'?+((v-1)*100).toFixed(2):v;
const fromUi=(k,v)=>k==='pct'?v/100:k==='x'?1+v/100:v;
function fieldHTML(sec,[key,label,kind,help,step]){
  const id=`set_${sec}_${key}`;let inp;
  if(kind==='bool')inp=`<select id="${id}"><option value="true">On</option><option value="false">Off</option></select>`;
  else if(kind.startsWith('select:'))inp=`<select id="${id}">${kind.slice(7).split('|').map(o=>{const[v,l]=o.split('=');return `<option value="${esc(v)}">${esc(l||v)}</option>`}).join('')}</select>`;
  else if(kind==='text'||kind==='secret')inp=`<input type="${kind==='secret'?'password':'text'}" id="${id}" autocomplete="off" spellcheck="false">`;
  else inp=`<input type="number" id="${id}" step="${step||'any'}">`;
  return `<div class="f ${kind==='text'||kind==='secret'?'wide':''}"><label for="${id}">${esc(label)}${kind==='pct'||kind==='x'?' %':''}</label>${inp}${help?`<small>${esc(help)}</small>`:''}</div>`;
}
$('#setGrid').innerHTML=Object.entries(SPEC).map(([sec,[title,fields]])=>`<div class="card"><div class="row" style="justify-content:space-between"><h3>${title}</h3><div class="row">${sec==='alerts'?'<button class="btn small" id="alertTest">Send test</button>':''}<button class="btn small" data-reset="${sec}">Reset</button></div></div><div class="fields">${fields.map(f=>fieldHTML(sec,f)).join('')}</div></div>`).join('');
function readField(sec,[key,,kind]){
  const v=$(`#set_${sec}_${key}`).value;
  if(kind==='bool')return v==='true';
  if(kind.startsWith('select:')||kind==='text'||kind==='secret')return v;
  return v===''?null:fromUi(kind,+v);
}
function fillSettings(s){
  for(const[sec,[,fields]]of Object.entries(SPEC))for(const[key,,kind]of fields){
    const el=$(`#set_${sec}_${key}`),v=s[sec][key];
    el.value=kind==='bool'?String(v):(typeof v==='number'?toUi(kind,v):v);
    el.dataset.orig=el.value;el.classList.remove('changed');
  }
  $('#saveBar').classList.remove('on');
}
function markChanged(e){const el=e.target;if(!el.id||!el.id.startsWith('set_'))return;el.classList.toggle('changed',el.value!==el.dataset.orig);$('#saveBar').classList.toggle('on',!!document.querySelector('#setGrid .changed'))}
$('#setGrid').addEventListener('input',markChanged);
$('#setGrid').addEventListener('change',markChanged);
$('#setGrid').onclick=async e=>{
  const r=e.target.closest('[data-reset]');
  if(r){if(!(await confirmDlg('Reset '+SPEC[r.dataset.reset][0]+'?','Every value in this section goes back to its default.','Reset')))return;
    try{ST.settings=await api('/api/settings/reset?section='+r.dataset.reset,{method:'POST'});fillSettings(ST.settings);toast('Reset to defaults')}catch(err){toast(err.message,true)}}
  if(e.target.id==='alertTest'){try{const res=await api('/api/alerts/test',{method:'POST'});toast('Test sent: '+Object.entries(res).map(([k,v])=>k+' '+(v===200||v===204?'✓':v)).join(' · '))}catch(err){toast(err.message,true)}}
};
$('#setUndo').onclick=()=>fillSettings(ST.settings);
$('#setSave').onclick=async()=>{
  const patch={};
  for(const[sec,[,fields]]of Object.entries(SPEC))for(const f of fields){if($(`#set_${sec}_${f[0]}`).classList.contains('changed')){const v=readField(sec,f);if(v!==null)(patch[sec]=patch[sec]||{})[f[0]]=v}}
  try{ST.settings=await api('/api/settings',{method:'POST',body:patch});fillSettings(ST.settings);toast('Settings saved')}catch(e){toast(e.message,true)}
};
async function saveQuick(patch){try{ST.settings=await api('/api/settings',{method:'POST',body:patch});fillSettings(ST.settings);toast('Saved')}catch(e){toast(e.message,true)}}
function renderKeys(){
  const k=ST.status&&ST.status.keys;if(!k)return;
  const it=(ok,label,note)=>`<div class="row" style="gap:8px;margin:4px 0"><span class="tag ${ok?'good':'warn'}">${ok?'✓':'—'}</span><span>${label}</span><span class="sub">${note}</span></div>`;
  $('#keyCard').innerHTML=`<h3>GMGN connection</h3><div class="sub" style="margin-bottom:8px">Keys stay on this computer in <span class="mono">${esc(k.env_path)}</span>. Kraken only listens on 127.0.0.1.</div>`+
   it(k.cli,'gmgn-cli installed',k.cli?'':'npm install -g gmgn-cli')+it(k.api_key,'API key',k.api_key?'live market data':'demo data until set: run python -m kraken setup')+it(k.private_key,'Signing key',k.private_key?'LIVE trading possible':'paper trading only (that\'s fine)');
}

/* loop */
async function refresh(force){
  try{
    if(!ST.settings||force){ST.settings=await api('/api/settings');fillSettings(ST.settings)}
    await loadStatus();
    const v=ST.view;
    if(v==='hunter')await loadHunter();else if(v==='screen')await loadScreen();else if(v==='positions')await loadPositions();
    else if(v==='learn')await loadLearn();else if(v==='activity')await loadActivity();else if(v==='settings')renderKeys();
  }catch(e){$('#srcTxt').textContent='backend offline';$('#srcPill').className='pill';}
}
try{const v=localStorage.getItem('kraken.view');if(v&&$('#v-'+v))ST.view=v;$('#sRej').checked=localStorage.getItem('kraken.rej')!=='0'}catch(e){}
show(ST.view);runBT();
setInterval(()=>{if(!document.hidden&&ST.view!=='settings')refresh()},6000);
