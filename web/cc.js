'use strict';
/* kraken command center: Discover, smart-money tape, CA research, wallet research, orders. Uses helpers from app.js. */
/* block explorer links: Solscan on SOL, the matching *scan on EVM chains */
const EXPL={sol:['Solscan','https://solscan.io/account/','https://solscan.io/token/','https://solscan.io/tx/'],
  bsc:['BscScan','https://bscscan.com/address/','https://bscscan.com/token/','https://bscscan.com/tx/'],
  base:['BaseScan','https://basescan.org/address/','https://basescan.org/token/','https://basescan.org/tx/'],
  eth:['Etherscan','https://etherscan.io/address/','https://etherscan.io/token/','https://etherscan.io/tx/']};
function scanUrl(kind,id){const e=EXPL[chainNow()]||EXPL.sol;return (kind==='token'?e[2]:kind==='tx'?e[3]:e[1])+encodeURIComponent(id||'')}
const scanName=()=>(EXPL[chainNow()]||EXPL.sol)[0];
/* small ↗ icon link that opens the explorer without triggering the row's own click */
const scanIcon=(kind,id)=>id?`<a class="scan" href="${scanUrl(kind,id)}" target="_blank" rel="noopener noreferrer" title="Open on ${scanName()}" onclick="event.stopPropagation()">↗</a>`:'';
const CC={feed:'all',tapeKinds:'',token:null,wallet:null,jobs:{}};
const short=a=>a?esc(a.slice(0,4))+'…'+esc(a.slice(-4)):'';
const safeBadge=s=>s==null?'<span class="safe">—</span>':`<span class="safe ${s>=80?'g':s>=60?'y':'r'}">${s}</span>`;
const ageTxt=m=>m==null?'—':fdur(m);
const chainNow=()=>(ST.settings&&ST.settings.chain)||'sol';
function needKey(el,msg){el.innerHTML=`<div class="empty card"><div class="big" style="font-size:34px">🔑</div>${esc(msg)}<br><br><button class="btn primary" onclick="openWizard(true)">Connect GMGN</button></div>`}
function copy(t){try{navigator.clipboard.writeText(t);toast('Copied')}catch(e){}}

/* routing: #/token/ADDR and #/wallet/ADDR so the browser back button works */
function goToken(a){location.hash='#/token/'+a}
function goWallet(a){location.hash='#/wallet/'+a}
window.addEventListener('hashchange',route);
function route(){
  const m=location.hash.match(/^#\/(token|wallet)\/([A-Za-z0-9]+)$/);
  if(!m)return false;
  ST.view=m[1];
  document.querySelectorAll('#nav button').forEach(b=>b.classList.remove('on'));
  document.querySelectorAll('.view').forEach(s=>s.classList.toggle('on',s.id==='v-'+m[1]));
  window.scrollTo(0,0);
  m[1]==='token'?openToken(m[2]):openWallet(m[2]);
  return true;
}
document.addEventListener('click',e=>{
  const t=e.target.closest('[data-tok]');if(t){e.preventDefault();goToken(t.dataset.tok);return}
  const w=e.target.closest('[data-wal]');if(w){e.preventDefault();goWallet(w.dataset.wal);return}
  const g=e.target.closest('[data-v-go]');if(g){location.hash='';show(g.dataset.vGo)}
});

/* search box */
$('#searchForm').onsubmit=async e=>{
  e.preventDefault();const q=$('#q').value.trim();if(!q)return;
  try{const r=await api('/api/search?q='+encodeURIComponent(q));
    if(r.chain&&r.chain!==chainNow()){ST.settings.chain=r.chain;$('#chainSel').value=r.chain;renderChain();CC.disc=null;CC.tape=[];toast(`That address is on ${r.chain.toUpperCase()}. Switched chain.`)}
    if(r.kind==='token')goToken(r.address);else if(r.kind==='wallet')goWallet(r.address);
    else showResults(r);
    $('#q').value='';
  }catch(err){toast(err.message,true)}
};
function showResults(r){
  ST.view='token';document.querySelectorAll('.view').forEach(s=>s.classList.toggle('on',s.id==='v-token'));
  $('#tokBody').innerHTML=`<button class="back" onclick="history.back()">← Back</button><h2 style="margin:0 0 6px">Results for “${esc(r.query)}”</h2>
   ${r.note?`<div class="banner on">${esc(r.note)}</div>`:''}
   ${r.results.some(x=>x.copycat_risk)?'<div class="banner on">Several tokens share this name. Copycats are common: the real one usually has the biggest market cap and the most holders. Check the CA before buying.</div>':''}
   <div class="tblwrap"><table class="tbl"><thead><tr><th>Token</th><th class="num">MC</th><th class="num">Liquidity</th><th class="num">Holders</th><th></th></tr></thead><tbody>
   ${r.results.length?r.results.map(t=>`<tr class="click" data-tok="${esc(t.address)}"><td><b>${esc(t.symbol)}</b> <span class="sub">${esc(t.name)}</span><br><span class="sub mono">${short(t.address)}</span></td><td class="num">${money(t.mcap)}</td><td class="num">${money(t.liquidity)}</td><td class="num">${t.holders||'—'}</td><td>${t.copycat_risk?'<span class="tag warn">same name</span>':''}</td></tr>`).join(''):'<tr><td colspan="5"><div class="empty">No matches. Paste the contract address instead.</div></td></tr>'}</tbody></table></div>`;
}

/* ── Discover ── */
const FEEDS=[['all','All'],['trending','Trending'],['new','New'],['almost bonded','Almost bonded'],['just bonded','Just bonded'],['hot search','Hot searches']];
$('#dChips').innerHTML=FEEDS.map(([k,l])=>`<button class="chip ${k==='all'?'on':''}" data-feed="${k}">${l}</button>`).join('');
$('#dChips').onclick=e=>{const b=e.target.closest('[data-feed]');if(!b)return;CC.feed=b.dataset.feed;document.querySelectorAll('#dChips .chip').forEach(c=>c.classList.toggle('on',c===b));renderDiscover()};
$('#dSafe').onchange=()=>{try{localStorage.setItem('kraken.safe',$('#dSafe').checked?'1':'0')}catch(e){};renderDiscover()};
try{$('#dSafe').checked=localStorage.getItem('kraken.safe')==='1'}catch(e){}
$('#dRefresh').onclick=()=>loadDiscover(true);
async function loadDiscover(force){
  try{CC.disc=await api('/api/discover'+(force?'?force=1':''));$('#dErr').classList.remove('on');}
  catch(e){CC.disc=null;$('#dTbl').innerHTML=`<tbody><tr><td><div class="empty"><div style="font-size:30px">🔑</div>${esc(e.message)}<br><br><button class="btn primary" onclick="openWizard(true)">Connect GMGN</button></div></td></tr></tbody>`;$('#dStatus').textContent='';return}
  const errs=Object.entries(CC.disc.errors||{}).filter(([k])=>k!=='call-outs');
  $('#dErr').innerHTML=errs.map(([k,v])=>`<b>${esc(k)}:</b> ${esc(v)}`).join('<br>');$('#dErr').classList.toggle('on',errs.length>0);
  $('#dStatus').textContent='updated '+ago(CC.disc.ts);
  renderDiscover();renderCallouts();
  await loadTapeMini();renderKpis();
}
function kpiTile(title,val,chip,chipUp,foot){return `<div class="tile"><div class="hd"><span class="k">${title}</span>${chip?`<span class="chg ${chipUp?'up':'down'}">${chipUp?'↗':'↘'} ${chip}</span>`:''}</div><div class="v">${val}</div><div class="s">${foot}</div></div>`}
function renderKpis(){
  const d=CC.disc;if(!d)return;const toks=d.tokens,n=toks.length,safe=toks.filter(t=>t.safety>=60).length;
  const fresh=toks.filter(t=>t.age_min!=null&&t.age_min<60).length;
  const tr=(CC.tape||[]).filter(r=>Date.now()/1000-r.ts<3600&&r.kind!=='follow');
  const buy=tr.filter(r=>r.side==='buy').reduce((s,r)=>s+r.usd,0),sell=tr.filter(r=>r.side==='sell').reduce((s,r)=>s+r.usd,0),net=buy-sell;
  const ps=(ST.status&&ST.status.positions)||{open:0,unrealized:0,exposure:0};
  const pnlPct=ps.exposure?ps.unrealized/ps.exposure:0;
  $('#dKpis').innerHTML=[
    kpiTile('Tokens tracked',n.toLocaleString(),fresh+' new <1h',true,'Trending, new launches, bonding and hot searches'),
    kpiTile('Pass quick safety',n?Math.round(safe/n*100)+' %':'—',`${n-safe} flagged`,safe/n>=.5,'Safety score 60 or higher'),
    kpiTile('Smart money net, 1h',(net<0?'−':'+')+money(Math.abs(net)),'buys '+money(buy),net>=0,`${tr.length} trades · sells ${money(sell)}`),
    kpiTile('Your positions',String(ps.open),ps.exposure?spct(pnlPct):'',pnlPct>=0,`Unrealized ${ps.unrealized>=0?'+':''}${(ps.unrealized||0).toFixed(4)} · ${ST.status&&ST.status.mode==='LIVE'?'LIVE':'paper'}`),
  ].join('');
}
function renderDiscover(){
  if(!CC.disc)return;
  let rows=CC.disc.tokens.filter(t=>CC.feed==='all'||t.sources.includes(CC.feed));
  if($('#dSafe').checked)rows=rows.filter(t=>t.safety>=60);
  if(CC.feed==='new')rows.sort((a,b)=>(a.age_min??1e9)-(b.age_min??1e9));
  $('#dTbl').innerHTML=`<thead><tr><th>Token</th><th title="Quick safety from GMGN's listing data. Open the token for the full score.">Safety</th><th class="num">MC</th><th class="num">1h</th><th class="num">Age</th><th class="num" title="Smart money / KOL holders">SM/KOL</th></tr></thead><tbody>`+
   (rows.length?rows.slice(0,150).map(t=>`<tr class="click" data-tok="${esc(t.address)}">
     <td><div class="tok"><b>${esc(t.symbol)} <span class="sub" style="font-weight:400;font-size:11px">${esc(t.sources[0])}${t.progress!=null&&(t.sources.includes('new')||t.sources.includes('almost bonded'))?' · '+pct(t.progress)+' bonded':''}</span></b><span class="sub" style="font-size:11px;white-space:normal">${t.flags.length?t.flags.slice(0,2).map(f=>`<span class="${t.safety<60?'down':''}">${esc(f)}</span>`).join(' · '):'<span class="up">no flags</span>'}</span></div></td>
     <td>${safeBadge(t.safety)}</td><td class="num">${money(t.mcap)}</td>
     <td class="num ${t.chg_1h>=0?'up':'down'}">${t.chg_1h?spct(t.chg_1h,0):'—'}</td><td class="num">${ageTxt(t.age_min)}</td>
     <td class="num">${t.smart}/${t.kol}</td></tr>`).join('')
   :'<tr><td colspan="6"><div class="empty">Nothing in this feed right now.</div></td></tr>')+'</tbody>';
}
function renderCallouts(){
  const c=(CC.disc&&CC.disc.callouts)||[];
  $('#dCalls').innerHTML=c.length?c.slice(0,6).map(x=>{const t=x.token||x;const a=t.address||x.token_address;const s=t.symbol||x.symbol||'?';
    return `<div class="pr"><span><a href="#" data-tok="${esc(a||'')}"><b>${esc(s)}</b></a> <span class="sub">by ${esc((x.caller&&x.caller.name)||x.wallet_name||short(x.wallet||x.wallet_address||''))}</span></span><span class="mono ${(x.multiplier||x.multiple||1)>=1?'up':'down'}">${x.multiplier||x.multiple?(+(x.multiplier||x.multiple)).toFixed(1)+'×':''}</span></div>`}).join('')
   :`<div class="sub">${esc((CC.disc&&CC.disc.errors&&CC.disc.errors['call-outs'])||'No call-outs yet.')}</div>`;
}
function tapeRow(r){return `<div class="t"><span class="s ${esc(r.side)}">${esc(r.side||'')}</span><span><a href="#" data-tok="${esc(r.token||'')}"><b>${esc(r.symbol||short(r.token))}</b></a> <span class="sub">${money(r.usd)} · <a href="#" data-wal="${esc(r.maker||'')}">${esc(r.who||short(r.maker))}</a></span></span><span class="sub mono">${esc(r.kind==='sm'?'smart':r.kind==='kol'?'KOL':'follow')} · ${ago(r.ts)}${r.h?' '+scanIcon('tx',r.h):''}</span></div>`}
async function loadTapeMini(){
  try{const t=await api('/api/tape');CC.tape=t.trades;
    $('#dTape').innerHTML=t.trades.length?t.trades.slice(0,30).map(tapeRow).join(''):'<div class="sub">Trades appear within a minute of kraken starting.</div>';
    MiniGraph.update(t.trades);renderHeat(t.trades);
  }catch(e){}
  try{const p=await api('/api/positions');const o=p.open;
    $('#dPos').innerHTML=o.length?o.slice(0,6).map(x=>`<div class="pr"><a href="#" data-tok="${esc(x.address)}"><b>${esc(x.symbol)}</b></a><span class="sub">${x.size} · ${x.mode==='LIVE'?'live':'paper'}</span><span class="chg ${x.pnl_pct>=0?'up':'down'}">${x.pnl_pct>=0?'↗':'↘'} ${spct(x.pnl_pct)}</span></div>`).join('')+(o.length>6?`<div class="sub" style="margin-top:6px">+${o.length-6} more</div>`:''):'<div class="sub">No open positions. Research a token and buy from its page.</div>';
  }catch(e){}
  if(CC.disc)renderKpis();
}
/* smart-money flow heatmap: top tokens × last 60 minutes in 5-minute buckets */
function renderHeat(trades){
  const now=Date.now()/1000,win=trades.filter(r=>now-r.ts<3600&&r.token&&r.kind!=='follow');
  const by={};for(const r of win){const g=by[r.token]||(by[r.token]={sym:r.symbol,addr:r.token,cells:Array(12).fill(0),tot:0});const i=Math.min(11,Math.floor((now-r.ts)/300));const v=(r.side==='buy'?1:-1)*r.usd;g.cells[11-i]+=v;g.tot+=Math.abs(r.usd)}
  const rows=Object.values(by).sort((a,b)=>b.tot-a.tot).slice(0,8);
  if(!rows.length){$('#mHeat').innerHTML='<div class="sub" style="padding:20px 0">Smart-money trades show up here within a few minutes of kraken starting.</div>';return}
  const mx=Math.max(...rows.flatMap(r=>r.cells.map(Math.abs)),1);
  $('#mHeat').innerHTML=`<div class="heat">${rows.map(r=>`<div class="lb" data-tok="${esc(r.addr)}" title="${esc(r.sym)}">${esc(r.sym||short(r.addr))}</div>`+r.cells.map(v=>`<div class="c ${v>0?'b':v<0?'s':''}" style="${v?`opacity:${(.22+.78*Math.sqrt(Math.abs(v)/mx)).toFixed(2)}`:''}" title="${v?(v>0?'net buy ':'net sell ')+money(Math.abs(v)):'no trades'}"></div>`).join('')).join('')}
    <div></div>${Array.from({length:12},(_,i)=>`<div class="ax">${i%3===0?(i===0?'-60m':'-'+(60-i*5)+'m'):''}</div>`).join('')}</div>
    <div class="row" style="gap:12px;margin-top:10px;font-size:11px;color:var(--dim)"><span><i style="display:inline-block;width:10px;height:10px;border-radius:3px;background:var(--glow);vertical-align:-1px"></i> net buying</span><span><i style="display:inline-block;width:10px;height:10px;border-radius:3px;background:var(--glow2);vertical-align:-1px"></i> net selling</span></div>`;
}
/* live smart-money network: wallets → tokens they traded in the last hour */
const MiniGraph={
  nodes:new Map(),
  init(){const el=$('#mGraph');if(!el||typeof d3==='undefined'||this.svg)return!!this.svg;
    this.svg=d3.select(el).insert('svg',':first-child');this.g=this.svg.append('g');this.lg=this.g.append('g');this.ng=this.g.append('g');
    this.svg.append('defs').html('<filter id="mglow"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>');
    this.svg.call(d3.zoom().scaleExtent([.3,3]).on('zoom',e=>this.g.attr('transform',e.transform)));
    this.sim=d3.forceSimulation().force('link',d3.forceLink().id(d=>d.id).distance(55).strength(.5)).force('charge',d3.forceManyBody().strength(-70).distanceMax(220))
      .force('collide',d3.forceCollide().radius(d=>d.r+4)).force('x',d3.forceX(()=>el.clientWidth/2).strength(.06)).force('y',d3.forceY(()=>el.clientHeight/2).strength(.06))
      .on('tick',()=>{const W=el.clientWidth,H=el.clientHeight;for(const d of this.sim.nodes()){d.x=Math.max(d.r+4,Math.min(W-d.r-4,d.x));d.y=Math.max(d.r+4,Math.min(H-d.r-16,d.y))}this.lg.selectAll('line').attr('x1',l=>l.source.x).attr('y1',l=>l.source.y).attr('x2',l=>l.target.x).attr('y2',l=>l.target.y);this.ng.selectAll('g').attr('transform',d=>`translate(${d.x},${d.y})`)});
    return true},
  update(trades){
    if(!this.init())return;
    const el=$('#mGraph'),now=Date.now()/1000,win=trades.filter(r=>now-r.ts<3600&&r.token&&r.maker);
    const tok={};for(const r of win){const g=tok[r.token]||(tok[r.token]={id:r.token,label:r.symbol||short(r.token),type:'token',usd:0});g.usd+=r.usd}
    const keep=new Set(Object.values(tok).sort((a,b)=>b.usd-a.usd).slice(0,12).map(t=>t.id));
    const links={},wal={};
    for(const r of win){if(!keep.has(r.token))continue;const w=wal[r.maker]||(wal[r.maker]={id:r.maker,label:r.who||short(r.maker),type:r.kind,usd:0});w.usd+=r.usd;
      const k=r.maker+'|'+r.token;const l=links[k]||(links[k]={source:r.maker,target:r.token,usd:0,buy:0});l.usd+=r.usd;if(r.side==='buy')l.buy+=r.usd}
    const wallets=Object.values(wal).sort((a,b)=>b.usd-a.usd).slice(0,45),wk=new Set(wallets.map(w=>w.id));
    const data=[...Object.values(tok).filter(t=>keep.has(t.id)),...wallets].map(n=>{const o=this.nodes.get(n.id);n.r=n.type==='token'?6+Math.min(14,Math.sqrt(n.usd)/12):4+Math.min(6,Math.sqrt(n.usd)/25);
      if(o){n.x=o.x;n.y=o.y;n.vx=o.vx;n.vy=o.vy}else{n.x=el.clientWidth/2+(Math.random()-.5)*120;n.y=el.clientHeight/2+(Math.random()-.5)*120}return n});
    this.nodes=new Map(data.map(n=>[n.id,n]));
    const ls=Object.values(links).filter(l=>wk.has(l.source)).map(l=>({...l,key:l.source+'|'+l.target}));
    if(!data.length){this.ng.selectAll('*').remove();this.lg.selectAll('*').remove();if(!el.querySelector('.empty-msg'))el.insertAdjacentHTML('beforeend','<div class="empty-msg sub" style="position:absolute;inset:0;display:grid;place-items:center">Waiting for smart-money trades…</div>');return}
    el.querySelectorAll('.empty-msg').forEach(x=>x.remove());
    const tip=$('#mTip');
    const L=this.lg.selectAll('line').data(ls,l=>l.key);L.exit().remove();
    L.enter().append('line').merge(L).attr('stroke',l=>l.buy>=l.usd/2?'#ff5b37':'#8b8cff').attr('stroke-opacity',.45).attr('stroke-width',l=>.8+Math.min(3,Math.log10(1+l.usd)/1.5));
    const N=this.ng.selectAll('g').data(data,d=>d.id);N.exit().remove();
    const E=N.enter().append('g').style('cursor','pointer').call(d3.drag().on('start',(e,d)=>{if(!e.active)this.sim.alphaTarget(.3).restart();d.fx=d.x;d.fy=d.y}).on('drag',(e,d)=>{d.fx=e.x;d.fy=e.y}).on('end',(e,d)=>{if(!e.active)this.sim.alphaTarget(0);d.fx=d.fy=null}))
      .on('click',(e,d)=>d.type==='token'?goToken(d.id):goWallet(d.id))
      .on('mouseenter',(e,d)=>{tip.innerHTML=`<b>${esc(d.label)}</b><br><span class="sub">${d.type==='token'?'token':d.type==='sm'?'smart money':d.type==='kol'?'KOL':'followed wallet'} · ${money(d.usd)} traded in 1h</span>`;tip.style.display='block'})
      .on('mousemove',e=>{const r=el.getBoundingClientRect();tip.style.left=(e.clientX-r.left+12)+'px';tip.style.top=(e.clientY-r.top+12)+'px'}).on('mouseleave',()=>tip.style.display='none');
    E.append('circle');E.append('text').attr('text-anchor','middle').style('font-family','var(--mono)').style('font-size','10px').style('fill','#c9c9cf').style('pointer-events','none').style('paint-order','stroke').style('stroke','#0f0f11').style('stroke-width','3px');
    const M=E.merge(N);
    M.select('circle').attr('r',d=>d.r).attr('fill',d=>d.type==='token'?'#ff5b37':d.type==='kol'?'#c4c5ff':'#8b8cff').attr('filter',d=>d.type==='token'?'url(#mglow)':null).attr('stroke','#0f0f11').attr('stroke-width',1.5);
    M.select('text').attr('dy',d=>d.r+11).text(d=>d.type==='token'||d.usd>2000?d.label:'');
    this.sim.nodes(data);this.sim.force('link').links(ls);this.sim.alpha(this.started?.25:1).restart();this.started=true;
  }
};

/* ── Smart-money tape page ── */
const TK=[['','All'],['sm','Smart money'],['kol','KOLs'],['follow','Following']];
$('#tChips').innerHTML=TK.map(([k,l])=>`<button class="chip ${k===''?'on':''}" data-k="${k}">${l}</button>`).join('');
$('#tChips').onclick=e=>{const b=e.target.closest('[data-k]');if(!b)return;CC.tapeKinds=b.dataset.k;document.querySelectorAll('#tChips .chip').forEach(c=>c.classList.toggle('on',c===b));loadTape()};
async function loadTape(){
  const t=await api('/api/tape?kinds='+CC.tapeKinds);
  $('#tTbl').innerHTML=`<thead><tr><th>When</th><th>Side</th><th>Token</th><th class="num">Size</th><th>Wallet</th><th>Type</th></tr></thead><tbody>`+
   (t.trades.length?t.trades.map(r=>`<tr><td class="sub">${ago(r.ts)}</td><td class="${r.side==='buy'?'up':'down'}">${esc(r.side||'')}</td><td><a href="#" data-tok="${esc(r.token||'')}"><b>${esc(r.symbol||short(r.token))}</b></a></td><td class="num">${money(r.usd)}</td><td><a href="#" data-wal="${esc(r.maker||'')}">${esc(r.who||short(r.maker))}</a>${scanIcon('account',r.maker)}</td><td><span class="tag">${r.kind==='sm'?'smart':r.kind==='kol'?'KOL':'follow'}</span>${r.h?' '+scanIcon('tx',r.h):''}</td></tr>`).join('')
   :'<tr><td colspan="6"><div class="empty">No trades yet. They start flowing about a minute after kraken starts.</div></td></tr>')+'</tbody>';
  $('#fList').innerHTML=t.following.length?t.following.map(w=>`<div class="row" style="justify-content:space-between;padding:6px 0;border-bottom:1px solid #1f315066"><a href="#" data-wal="${esc(w.address)}">${esc(w.label||short(w.address))}</a><button class="btn small" data-unf="${esc(w.address)}">Unfollow</button></div>`).join(''):'<div class="sub" style="margin-top:6px">Not following anyone yet.</div>';
}
$('#fForm').onsubmit=async e=>{e.preventDefault();try{await api('/api/watchlist',{method:'POST',body:{address:$('#fAddr').value.trim(),label:$('#fLabel').value.trim()}});$('#fAddr').value='';$('#fLabel').value='';toast('Following');loadTape()}catch(err){toast(err.message,true)}};
$('#fList').onclick=async e=>{const b=e.target.closest('[data-unf]');if(!b)return;await api('/api/watchlist/remove',{method:'POST',body:{address:b.dataset.unf}});loadTape()};

/* ── shared: price chart + GMGN script jobs ── */
function chartSVG(pts,h=160){
  if(!pts||pts.length<2)return '<div class="sub" style="padding:30px;text-align:center">Not enough trading history to draw a chart yet.</div>';
  const W=640,H=h,P=8,lg=v=>Math.log(Math.max(v,1e-18));
  const hs=pts.map(p=>p[1]),ls=pts.map(p=>p[2]),top=lg(Math.max(...hs)),bot=lg(Math.min(...ls)),span=(top-bot)||1;
  const y=v=>P+(H-2*P)*(1-(lg(v)-bot)/span),x=i=>P+(W-2*P)*i/(pts.length-1);
  const line=pts.map((p,i)=>`${i?'L':'M'}${x(i).toFixed(1)},${y(p[0]).toFixed(1)}`).join('');
  const area=line+`L${x(pts.length-1).toFixed(1)},${H-P}L${P},${H-P}Z`;
  const up=pts[pts.length-1][0]>=pts[0][0];
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Price chart"><defs><linearGradient id="cg" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${up?'#8b8cff':'#ff6a4d'}" stop-opacity=".28"/><stop offset="1" stop-color="${up?'#8b8cff':'#ff6a4d'}" stop-opacity="0"/></linearGradient></defs><path d="${area}" fill="url(#cg)"/><path d="${line}" fill="none" stroke="${up?'#8b8cff':'#ff6a4d'}" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>`;
}
const DEV_REASONS={peak_implausible:'GMGN reports an impossible peak market cap for this dev, so a score would be meaningless.',index_empty:'GMGN has no launch history for this dev.',too_few:'Too few launches to score.'};
async function runJob(kind,target,el,render){
  el.innerHTML='<span class="spin"></span> Starting GMGN analysis… this can take 1–3 minutes.';
  try{await api('/api/jobs',{method:'POST',body:{kind,target}})}catch(e){el.innerHTML=`<span class="down">${esc(e.message)}</span>`;return}
  const poll=async()=>{
    if(!document.body.contains(el))return;
    const j=await api(`/api/jobs?kind=${kind}&target=${encodeURIComponent(target)}`).catch(()=>null);
    if(!j||j.status==='queued'||j.status==='running'){el.innerHTML=`<span class="spin"></span> ${j&&j.status==='queued'?'Waiting for another analysis to finish…':'Running GMGN analysis…'} <span class="sub">${j?Math.round(Date.now()/1000-j.started)+'s':''}</span>`;setTimeout(poll,3000);return}
    if(j.status==='error'){el.innerHTML=`<span class="down">Analysis failed: ${esc(j.error||'unknown error')}</span>`;return}
    el.innerHTML=render(j.output);
  };
  poll();
}
function devScoreHTML(o){
  if(!o)return '<span class="sub">No result.</span>';
  if(!o.scored)return `<div class="sub">${esc(DEV_REASONS[o.reason]||('Not scored: '+o.reason))}</div><div class="kv" style="margin-top:8px"><div>Launches<b>${(o.launches||0).toLocaleString()}</b></div><div>Bonded<b>${(o.graduated||0).toLocaleString()}</b></div><div>Still on curve<b>${(o.on_curve||0).toLocaleString()}</b></div></div>`;
  const s=o.score??o.dev_score??o.total;
  const keys=Object.entries(o).filter(([k,v])=>typeof v==='number'&&!/score|ts|time/.test(k)).slice(0,9);
  return `<div class="row"><span class="big ${s>=60?'up':s>=40?'':'down'}">${s!=null?Math.round(s):'—'}</span><span class="sub">/ 100 dev score from GMGN's model</span></div><div class="kv" style="margin-top:10px">${keys.map(([k,v])=>`<div>${esc(k.replace(/_/g,' '))}<b>${Math.abs(v)<10&&v%1?v.toFixed(2):Math.round(v).toLocaleString()}</b></div>`).join('')}</div>`;
}
const reportHTML=t=>`<div class="report">${esc(t||'')}</div>`;


/* ── trading chart (TradingView Lightweight Charts, Apache-2.0) ── */
const TV={
  open(addr,res){this.addr=addr;$('#tvTf').onclick=e=>{const b=e.target.closest('[data-res]');if(!b)return;document.querySelectorAll('#tvTf button').forEach(x=>x.classList.toggle('on',x===b));this.load(b.dataset.res)};this.load(res)},
  async load(res){
    const box=$('#tvBox'),msg=$('#tvMsg');if(!box)return;
    if(typeof LightweightCharts==='undefined'){msg.textContent='The chart library needs an internet connection.';return}
    msg.style.display='flex';msg.innerHTML='<span class="spin"></span> Loading chart…';
    let d;try{d=await api(`/api/candles/${encodeURIComponent(this.addr)}?res=${res}`)}catch(e){msg.textContent=e.message;return}
    if(CC.token!==this.addr)return;
    const raw=d.candles;if(raw.length<3){msg.textContent='Not enough trading history on this timeframe yet. Try a shorter one.';return}
    msg.style.display='none';
    if(this.chart){this.chart.remove();this.chart=null}
    const css=getComputedStyle(document.documentElement);
    const chart=LightweightCharts.createChart(box,{autoSize:true,
      layout:{background:{type:'solid',color:'transparent'},textColor:'#9b9ba2',fontFamily:'JetBrains Mono, monospace',fontSize:11},
      grid:{vertLines:{color:'#ffffff0a'},horzLines:{color:'#ffffff0a'}},
      rightPriceScale:{borderColor:'#26262a',scaleMargins:{top:.08,bottom:.06}},
      timeScale:{borderColor:'#26262a',timeVisible:true,secondsVisible:false,rightOffset:6,barSpacing:7},
      crosshair:{mode:LightweightCharts.CrosshairMode.Normal,vertLine:{color:'#9b9ba255',labelBackgroundColor:'#242427'},horzLine:{color:'#9b9ba255',labelBackgroundColor:'#242427'}},
      localization:{priceFormatter:fmtPx}});
    this.chart=chart;
    const bars=raw.map(([t,o,h,l,c])=>({time:t,open:o,high:h,low:l,close:c}));
    const cs=chart.addCandlestickSeries({upColor:'#8b8cff',downColor:'#ff6a4d',borderUpColor:'#8b8cff',borderDownColor:'#ff6a4d',wickUpColor:'#8b8cff',wickDownColor:'#ff6a4d',priceFormat:{type:'custom',formatter:fmtPx,minMove:1e-12}});
    cs.setData(bars);this.cs=cs;this.bars=bars;this.res=res;
    const closes=bars.map(b=>b.close),ma=(n)=>bars.map((b,i)=>i>=n-1?{time:b.time,value:closes.slice(i-n+1,i+1).reduce((a,x)=>a+x,0)/n}:null).filter(Boolean);
    const MAS=[[20,'#ff5b37'],[50,'#8b8cff'],[200,'#3ddc84']].filter(([n])=>bars.length>n+2);
    const maS={},maV={};for(const [n,col] of MAS){const data=ma(n);maV[n]=new Map(data.map(x=>[x.time,x.value]));maS[n]=chart.addLineSeries({color:col,lineWidth:1.5,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});maS[n].setData(data)}
    // trendlines through the two most recent swing highs (resistance) and swing lows (support)
    const piv=(isHigh)=>{const k=Math.max(3,Math.round(bars.length/40)),out=[];for(let i=k;i<bars.length-k;i++){const v=isHigh?bars[i].high:bars[i].low;let ok=true;for(let j=i-k;j<=i+k;j++){if(j===i)continue;const w=isHigh?bars[j].high:bars[j].low;if(isHigh?w>v:w<v){ok=false;break}}if(ok)out.push(i)}return out};
    const line=(idx,isHigh,col)=>{if(idx.length<2)return;const[a,b]=idx.slice(-2),va=isHigh?bars[a].high:bars[a].low,vb=isHigh?bars[b].high:bars[b].low,slope=(vb-va)/(b-a);const end=bars.length-1,vEnd=vb+slope*(end-b);if(vEnd<=0)return;
      const s=chart.addLineSeries({color:col,lineWidth:1,lineStyle:LightweightCharts.LineStyle.Solid,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});s.setData([{time:bars[a].time,value:va},{time:bars[end].time,value:vEnd}])};
    line(piv(true),true,'#c9c9cf88');line(piv(false),false,'#c9c9cf88');
    chart.timeScale().fitContent();
    const leg=$('#tvLeg'),last=bars[bars.length-1];
    const show=(b,i)=>{if(!b)return;const prev=i>0?bars[i-1].close:b.open,ch=b.close/prev-1;
      leg.innerHTML=`<span>O <b>${fmtPx(b.open)}</b></span><span>H <b>${fmtPx(b.high)}</b></span><span>L <b>${fmtPx(b.low)}</b></span><span>C <b class="${ch>=0?'up':'down'}">${fmtPx(b.close)}</b></span><span class="${ch>=0?'up':'down'}">${spct(ch,2)}</span>`+
        MAS.map(([n,col])=>{const v=maV[n].get(b.time);return v!=null?`<span style="color:${col}">MA${n} <b>${fmtPx(v)}</b></span>`:''}).join('')};
    show(last,bars.length-1);
    const idx=new Map(bars.map((b,i)=>[b.time,i]));
    chart.subscribeCrosshairMove(p=>{const b=p&&p.time!=null?bars[idx.get(p.time)]:null;show(b||last,b?idx.get(p.time):bars.length-1)});
    this.trade();this.syncPos();
    clearInterval(this.timer);this.timer=setInterval(()=>{if(CC.token===this.addr&&document.body.contains($('#tvBox')))this.syncPos();else clearInterval(this.timer)},8000);
  },
  /* corner trade box: buy adds to the position (weighted average entry), sells take 25/50/100% */
  trade(){
    const box=$('#tvBox');if(!box||$('#tvTrade'))return;
    const live=ST.status&&ST.status.mode==='LIVE',nat=chainNow()==='sol'?'SOL':chainNow()==='bsc'?'BNB':'ETH',def=(ST.settings&&ST.settings.risk.buy_size)||0.1;
    box.insertAdjacentHTML('beforeend',`<div class="tvtrade" id="tvTrade">
      <div class="row" style="justify-content:space-between;gap:6px"><b style="font-size:12px">Quick trade</b><span class="tag ${live?'bad':''}" style="margin:0">${live?'LIVE':'paper'}</span></div>
      <div class="tvsize"><input id="tqSize" type="number" step="0.01" min="0" value="${def}" aria-label="Size in ${nat}"><span>${nat}</span></div>
      <div class="tvq">${[0.1,0.5,1].map(v=>`<button data-sz="${v}">${v}</button>`).join('')}</div>
      <button class="btn primary tvbuy" id="tqBuy">Buy</button>
      <div class="tvsell">${[25,50,100].map(v=>`<button data-sell="${v}">Sell ${v===100?'all':v+'%'}</button>`).join('')}</div>
      <div class="tvpos" id="tqPos"></div></div>`);
    $('#tvTrade').onclick=e=>e.stopPropagation();
    $('#tvTrade').querySelectorAll('[data-sz]').forEach(b=>b.onclick=()=>{$('#tqSize').value=b.dataset.sz});
    $('#tqBuy').onclick=async()=>{const sz=parseFloat($('#tqSize').value);if(!(sz>0)){toast('Enter a size',true);return}
      const sym=(document.querySelector('.hero h2')||{}).firstChild?.textContent?.trim()||'?';
      if(live&&!(await confirmDlg(`Buy ${esc(sym)} for real?`,`Swap <b>${sz} ${nat}</b> into ${esc(sym)}. This is irreversible.`,'Buy now')))return;
      try{const p=await api('/api/buy',{method:'POST',body:{address:this.addr,symbol:sym,size:sz,source:'chart'}});toast(`${p.mode==='LIVE'?'Bought':'Paper buy'} ${sz} ${nat} · avg ${fmtPx(p.entry_price)}`);this.syncPos();loadStatus()}catch(err){toast(err.message,true)}};
    $('#tvTrade').querySelectorAll('[data-sell]').forEach(b=>b.onclick=async()=>{const p=this.pos;if(!p){toast('No open position on this token',true);return}
      const pct=+b.dataset.sell;if(p.mode==='LIVE'&&!(await confirmDlg(`Sell ${pct}% for real?`,`Sells ${pct}% of your ${esc(p.symbol)} position with a real swap.`,'Sell')))return;
      try{const q=await api('/api/sell',{method:'POST',body:{id:p.id,pct,reason:'chart'}});toast(`Sold ${pct}% · realized ${(q.realized>=0?'+':'')}${(q.realized||0).toFixed(4)} ${nat}`);this.syncPos();loadStatus()}catch(err){toast(err.message,true)}});
  },
  async syncPos(){
    let d;try{d=await api('/api/positions')}catch(e){return}
    const p=d.open.find(x=>x.address===this.addr)||null;this.pos=p;
    const nat=chainNow()==='sol'?'SOL':chainNow()==='bsc'?'BNB':'ETH';
    if(this.avgLine&&this.cs){try{this.cs.removePriceLine(this.avgLine)}catch(e){}this.avgLine=null}
    const closed=d.closed.find(x=>x.address===this.addr);
    const fills=(p&&p.fills)||(closed&&closed.fills)||[];
    if(this.cs&&this.bars&&this.bars.length){
      const step=this.bars.length>1?this.bars[1].time-this.bars[0].time:60,first=this.bars[0].time,lastT=this.bars[this.bars.length-1].time;
      const marks=fills.filter(f=>f.ts>=first-step).map(f=>{const tt=Math.min(lastT,first+Math.floor((f.ts-first)/step)*step);const buy=f.side==='buy';
        return {time:tt,position:buy?'belowBar':'aboveBar',color:buy?'#8b8cff':'#ff6a4d',shape:buy?'arrowUp':'arrowDown',text:buy?`B ${+f.size.toFixed(3)}`:`S ${f.pct?f.pct+'%':''}`}}).sort((a,b)=>a.time-b.time);
      this.cs.setMarkers(marks);
      if(p){const up=p.pnl_pct>=0;this.avgLine=this.cs.createPriceLine({price:p.entry_price,color:up?'#8b8cff':'#ff6a4d',lineWidth:1,lineStyle:LightweightCharts.LineStyle.Dashed,axisLabelVisible:true,
        title:`AVG ${spct(p.pnl_pct,1)} · ${p.pnl>=0?'+':''}${p.pnl.toFixed(4)} ${nat}`})}
    }
    const el=$('#tqPos');if(!el)return;
    el.innerHTML=p?`<div class="kv2"><span>Size</span><b>${+p.size.toFixed(4)} ${nat}</b></div><div class="kv2"><span>Avg entry</span><b>${fmtPx(p.entry_price)}</b></div>
      <div class="kv2"><span>Now</span><b>${fmtPx(p.last_price)}</b></div><div class="kv2"><span>Unrealized</span><b class="${p.pnl>=0?'up':'down'}">${p.pnl>=0?'+':''}${p.pnl.toFixed(4)} (${spct(p.pnl_pct,1)})</b></div>
      ${p.realized?`<div class="kv2"><span>Realized</span><b class="${p.realized>=0?'up':'down'}">${p.realized>=0?'+':''}${p.realized.toFixed(4)}</b></div>`:''}<div class="sub" style="margin-top:4px">${(p.fills||[]).filter(f=>f.side==='buy').length} buys · ${p.mode==='LIVE'?'live':'paper'}</div>`
      :closed&&Date.now()/1000-(closed.exit_ts||0)<3600?`<div class="sub">Closed ${ago(closed.exit_ts)} · <b class="${closed.pnl>=0?'up':'down'}">${closed.pnl>=0?'+':''}${closed.pnl.toFixed(4)} ${nat}</b></div>`:'<div class="sub">No position yet. Buy to start; each buy updates your average entry.</div>';
  }
};
function fmtPx(v){if(v==null||!isFinite(v))return '—';const a=Math.abs(v),sg=v<0?'-':'';if(a>=1000)return sg+a.toLocaleString(undefined,{maximumFractionDigits:2});if(a>=1)return sg+a.toFixed(4);if(a===0)return '0';
  const z=Math.floor(-Math.log10(a));/* zeros right after the decimal point */return z>=5?sg+'0.0'+toSub(z)+Math.round(a*10**(z+4)):sg+a.toFixed(z+4)}
function toSub(n){return String(n).split('').map(d=>'₀₁₂₃₄₅₆₇₈₉'[+d]).join('')}

/* ── Token research (CA) ── */
async function openToken(addr){
  const el=$('#tokBody');CC.token=addr;
  el.innerHTML='<button class="back" onclick="history.back()">← Back</button><div class="empty card"><span class="spin"></span> Researching token… (about 5 seconds)</div>';
  let d;try{d=await api('/api/token/'+encodeURIComponent(addr))}catch(e){el.innerHTML='<button class="back" onclick="history.back()">← Back</button>';needKey(el.appendChild(document.createElement('div')),e.message);return}
  if(CC.token!==addr)return;
  if(d.chain&&d.chain!==chainNow()){ST.settings.chain=d.chain;$('#chainSel').value=d.chain;renderChain();CC.disc=null;CC.tape=[]}
  if(d.kind!=='token'){
    try{const r=await api('/api/search?q='+encodeURIComponent(addr));if(r.chain&&r.chain!==chainNow()){ST.settings.chain=r.chain;$('#chainSel').value=r.chain;renderChain();toast(`That token is on ${r.chain.toUpperCase()}. Switched chain.`);if(r.kind==='token'){openToken(addr);return}}}catch(e){}
    goWallet(addr);return}
  const t=d.token,dd=d.dd,h=d.holders,dv=d.dev;
  const band=dd.scored?dd.band:'not scored';
  const col=!dd.scored?'':dd.score>=80?'up':dd.score>=60?'':'down';
  const chg=k=>t.chg[k]==null?'—':`<span class="${t.chg[k]>=0?'up':'down'}">${spct(t.chg[k],t.chg[k]>9?0:1)}</span>`;
  const hrow=x=>`<tr><td><a href="#" data-wal="${esc(x.address)}">${esc(x.name||short(x.address))}</a>${scanIcon('account',x.address)} ${x.tags.map(g=>`<span class="tag">${esc(g.replace(/_/g,' '))}</span>`).join('')}</td><td class="num">${pct(x.pct,2)}</td><td class="num">${money(x.usd)}</td><td class="num ${x.profit>=0?'up':'down'}">${x.profit?(x.profit>=0?'+':'−')+money(Math.abs(x.profit)):'—'}</td><td class="num">${x.buys}/${x.sells}</td></tr>`;
  const htable=rows=>`<div class="tblwrap"><table class="tbl"><thead><tr><th>Wallet</th><th class="num">Holds</th><th class="num">Value</th><th class="num">P/L</th><th class="num">Buys/sells</th></tr></thead><tbody>${rows.length?rows.map(hrow).join(''):'<tr><td colspan="5"><div class="empty">None found.</div></td></tr>'}</tbody></table></div>`;
  const cnt=h.counts||{},st=h.stat||{};
  el.innerHTML=`<button class="back" onclick="history.back()">← Back</button>
  <div class="hero">${t.logo?`<img src="${esc(t.logo)}" alt="" referrerpolicy="no-referrer" onerror="this.remove()">`:''}<div><h2>${esc(t.symbol)} <span class="sub" style="font-size:14px">${esc(t.name)}</span></h2><div class="addr" onclick="copy('${esc(addr)}')" title="Copy">${esc(addr)} ⧉</div>
    <div class="row" style="gap:6px;margin-top:6px">${t.launchpad?`<span class="tag">${esc(t.launchpad)}</span>`:''}<span class="tag ${t.bonded?'good':'warn'}">${t.bonded?'bonded':'on bonding curve '+pct(t.progress)}</span>${t.created?`<span class="tag">age ${fdur((Date.now()/1000-t.created)/60)}</span>`:''}${Object.entries(t.links||{}).map(([k,v])=>`<a class="tag" href="${esc(k==='twitter_username'&&!/^https?:/.test(v)?'https://x.com/'+v:v)}" target="_blank" rel="noopener noreferrer">${k==='twitter_username'?'X':esc(k)} ↗</a>`).join('')}<a class="tag" href="https://gmgn.ai/${esc(chainNow())}/token/${encodeURIComponent(addr)}" target="_blank" rel="noopener noreferrer">GMGN ↗</a><a class="tag" href="${scanUrl('token',addr)}" target="_blank" rel="noopener noreferrer">${scanName()} ↗</a></div></div></div>
  <div class="tiles">${[['Price',t.price?'$'+Number(t.price).toPrecision(4):'—'],['Market cap',money(t.mcap)],['Liquidity',money(t.liquidity)],['Holders',(t.holders||0).toLocaleString()],['5m / 1h',chg('5m')+' · '+chg('1h')],['Vol 1h',money(t.vol['1h']),`${t.buys_1h} buys · ${t.sells_1h} sells`]].map(([k,v,s])=>`<div class="tile"><div class="k">${k}</div><div class="v">${v}</div>${s?`<div class="s">${s}</div>`:''}</div>`).join('')}</div>
  <div class="card tv" style="margin-bottom:14px">
    <div class="tvbar"><div class="tvleg" id="tvLeg"></div><div class="tvtf" id="tvTf">${['1m','5m','15m','1h','4h'].map(r=>`<button data-res="${r}" class="${r===(d.chart.bar_min===1?'1m':'15m')?'on':''}">${r}</button>`).join('')}</div></div>
    <div class="tvbox" id="tvBox"><div class="tvmsg" id="tvMsg"><span class="spin"></span> Loading chart…</div></div>
    ${d.chart.pattern?`<div class="row" style="margin-top:10px;gap:6px"><span class="tag">${esc(d.chart.pattern.pattern)}</span><span class="tag">chart score ${d.chart.pattern.score}</span><span class="sub">${d.chart.pattern.why.map(esc).join(' · ')}</span></div>`:''}
  </div>
  <div class="grid2">
    <div class="card"><h3>Safety score</h3><div class="row" style="margin:10px 0"><span class="big ${col}">${dd.scored?Math.round(dd.score):'—'}</span><div><b style="font-size:16px">${esc(band)}</b><div class="sub">${esc(dd.profile||dd.reason||'')}</div></div></div>
      ${dd.scored?`<div class="row" style="gap:6px">${Object.entries(dd.sections).map(([k,v])=>`<span class="tag ${v>=80?'good':v>=60?'warn':'bad'}">${k} ${Math.round(v)}</span>`).join('')}<span class="tag">${esc(dd.confidence)}</span></div>
      ${dd.caps.length?`<div class="sub" style="margin-top:8px">Capped: ${dd.caps.map(c=>esc(c.why)+' → max '+c.cap).join('; ')}</div>`:''}
      <ul class="dd" style="padding-left:16px;margin:10px 0 0">${dd.deductions.length?dd.deductions.map(x=>`<li><span class="m">${x.deduction}</span>${esc(x.why)}</li>`).join(''):'<li class="up">No deductions. Every check passed.</li>'}</ul>
      ${(dd.notes||[]).map(n=>`<div class="sub" style="margin-top:6px">ⓘ ${esc(n)}</div>`).join('')}`:''}
      <div class="sub" style="margin-top:10px">This measures whether you can buy and sell it safely, not whether the price will go up. Based on GMGN's contract due-diligence model.</div></div>
    <div class="card"><h3>Who launched it</h3>
      ${dv.address?`<div style="margin:8px 0"><a href="#" data-wal="${esc(dv.address)}" class="mono">${short(dv.address)}</a>${scanIcon('account',dv.address)} · <a href="#" data-wal="${esc(dv.address)}">open dev wallet + graph</a></div>`:''}
      <div class="kv">${[['Tokens launched',(dv.launched||0).toLocaleString()],['Bonded',(dv.bonded||0).toLocaleString()+(dv.bond_rate?` (${pct(dv.bond_rate,1)})`:'')],['Dev holds now',pct(dv.holds,1)],['Best launch',dv.best?esc(dv.best.symbol)+' · '+money(dv.best.ath_mc):'—'],['X renames',dv.x_renames],['Deleted-post tokens',dv.x_deleted]].map(([k,v])=>`<div>${k}<b>${v}</b></div>`).join('')}</div>
      ${dv.launched>=50?`<div class="banner on" style="margin-top:10px">This dev has launched ${(dv.launched||0).toLocaleString()} tokens. Serial launchers rarely hold a project up.</div>`:''}
      ${dv.recent&&dv.recent.length?`<div class="sub" style="margin:10px 0 4px">Recent launches</div><div class="tblwrap"><table class="tbl"><tbody>${dv.recent.slice(0,8).map(r=>`<tr class="click" data-tok="${esc(r.address)}"><td><b>${esc(r.symbol)}</b></td><td class="num">${money(r.mcap)}</td><td class="num">ATH ${r.ath_mc?money(r.ath_mc):'—'}</td><td>${r.bonded?'<span class="tag good">bonded</span>':'<span class="tag">curve</span>'}</td></tr>`).join('')}</tbody></table></div>`:''}
      ${dv.address?`<div class="row" style="margin-top:12px"><button class="btn small" id="dRun">Dev score (GMGN)</button><span class="sub">Rug history, dump timing, exits</span></div><div id="dOut" style="margin-top:10px"></div>`:''}</div>
  </div>
  <div class="card" style="margin-bottom:14px"><h3>Who holds it</h3>
      <div class="kv" style="margin:10px 0">${[['Top 10',pct(st.top_10_holder_rate)],['Dev holds',pct(st.creator_hold_rate,1)],['Bundlers',pct(st.top_bundler_trader_percentage)],['Snipers',pct(st.top70_sniper_hold_rate)],['Bots',pct(st.bot_degen_rate)],['Fresh wallets',pct(st.fresh_wallet_rate)]].map(([k,v])=>`<div>${k}<b>${v}</b></div>`).join('')}</div>
      <div class="row" style="gap:6px;margin-bottom:10px">${[['smart','smart money','good'],['kol','KOLs','good'],['sniper','snipers','warn'],['bundler','bundlers','warn'],['rat','rat traders','bad'],['fresh','fresh wallets','']].map(([k,l,c])=>cnt[k]?`<span class="tag ${c}">${cnt[k]} ${l}</span>`:'').join('')}</div>
      <div class="feedbar" id="hTabs"><button class="chip on" data-h="top">Top holders</button><button class="chip" data-h="smart">Smart money (${h.smart.length})</button><button class="chip" data-h="kol">KOLs (${h.kol.length})</button></div>
      <div id="hTbl">${htable(h.top)}</div>
      <div class="row" style="margin-top:12px"><button class="btn small" id="hRun">Deep holder analysis</button><span class="sub">GMGN's chip analysis: clusters, entry costs, who's selling</span></div><div id="hOut" style="margin-top:10px"></div></div>
  <div class="card buybox" id="buyBox"></div>`;
  $('#hTabs').onclick=e=>{const b=e.target.closest('[data-h]');if(!b)return;document.querySelectorAll('#hTabs .chip').forEach(c=>c.classList.toggle('on',c===b));$('#hTbl').innerHTML=htable(h[b.dataset.h])};
  $('#hRun').onclick=()=>runJob('holders',addr,$('#hOut'),reportHTML);
  if($('#dRun'))$('#dRun').onclick=()=>runJob('dev',dv.address,$('#dOut'),devScoreHTML);
  renderBuyBox(addr,t,dd);
  TV.open(addr,d.chart.bar_min===1?'1m':'15m');
}
function renderBuyBox(addr,t,dd){
  const live=ST.status&&ST.status.mode==='LIVE',size=ST.settings?ST.settings.risk.buy_size:0.05,nat=chainNow()==='sol'?'SOL':chainNow()==='bsc'?'BNB':'ETH';
  $('#buyBox').innerHTML=`<div class="row" style="justify-content:space-between"><h3>Trade ${esc(t.symbol)}</h3><span class="tag ${live?'bad':''}">${live?'LIVE · real funds':'SHADOW · paper'}</span></div>
   ${dd.scored&&dd.score<60?`<div class="banner red on" style="margin-top:10px">Safety score ${Math.round(dd.score)}: ${esc(dd.band)}. Read the deductions above before buying.</div>`:''}
   <div class="grid2" style="margin:12px 0 0">
    <div><div class="sub" style="margin-bottom:8px"><b>Buy now</b></div><div class="fields" style="margin-top:0">
      <div class="f"><label for="bSize">Size (${nat})</label><input id="bSize" type="number" step="0.01" value="${size}"></div>
      <div class="f"><label for="bTp">Take profit %</label><input id="bTp" type="number" step="10" placeholder="e.g. 100"><small>Sell all at +this %</small></div>
      <div class="f"><label for="bSl">Stop loss %</label><input id="bSl" type="number" step="5" placeholder="e.g. 30"><small>Sell all at −this %</small></div></div>
      <button class="btn primary" id="bGo" style="margin-top:10px">${live?'Buy (real)':'Paper buy'}</button>
      <div class="sub" style="margin-top:6px">${live?'Take profit and stop loss are placed on GMGN with the buy, so they run even when kraken is closed.':'Paper take profit and stop loss are filled by kraken while it runs.'}</div></div>
    <div><div class="sub" style="margin-bottom:8px"><b>Limit order</b> · current price ${t.price?'$'+Number(t.price).toPrecision(4):'—'}</div><div class="fields" style="margin-top:0">
      <div class="f"><label for="oType">Type</label><select id="oType"><option value="buy_low">Buy the dip (price falls to)</option><option value="buy_high">Buy the breakout (price rises to)</option><option value="take_profit">Sell at target</option><option value="stop_loss">Sell at stop</option></select></div>
      <div class="f"><label for="oMc">Trigger market cap $</label><input id="oMc" type="number" step="1000" placeholder="${Math.round(t.mcap||0)}"><small>Easier than price; kraken converts it</small></div>
      <div class="f"><label for="oExp">Expires (hours)</label><input id="oExp" type="number" value="24" step="1"></div></div>
      <button class="btn" id="oGo" style="margin-top:10px">Place ${live?'live':'paper'} order</button></div>
   </div>`;
  $('#bGo').onclick=async()=>{
    const tp=parseFloat($('#bTp').value),sl=parseFloat($('#bSl').value),sz=parseFloat($('#bSize').value);
    if(live&&!(await confirmDlg(`Buy ${esc(t.symbol)} for real?`,`Swap <b>${sz} ${nat}</b> into ${esc(t.symbol)}${tp?`, take profit at +${tp}%`:''}${sl?`, stop loss at −${sl}%`:''}. This is irreversible.`,'Buy now')))return;
    try{const p=await api('/api/buy',{method:'POST',body:{address:addr,symbol:t.symbol,size:sz||null,source:'research',take_profit:tp?tp/100:null,stop_loss:sl?sl/100:null}});toast(`${p.mode==='LIVE'?'Bought':'Paper buy'} ${p.symbol}`);loadStatus()}catch(e){toast(e.message,true)}
  };
  $('#oGo').onclick=async()=>{
    const mc=parseFloat($('#oMc').value),type=$('#oType').value;
    if(!mc||!t.mcap||!t.price){toast('Enter a trigger market cap',true);return}
    const trigger=t.price*mc/t.mcap;
    if(live&&!(await confirmDlg('Place a real limit order?',`${esc($('#oType').selectedOptions[0].text)} at ${money(mc)} market cap. It runs on GMGN until it fills or expires.`,'Place order')))return;
    try{const r=await api('/api/orders',{method:'POST',body:{address:addr,symbol:t.symbol,type,trigger_price:trigger,size:parseFloat($('#bSize').value)||null,expire_hours:parseFloat($('#oExp').value)||24}});toast((r.mode==='LIVE'?'Live':'Paper')+' order placed')}catch(e){toast(e.message,true)}
  };
}

/* ── Wallet research ── */
const ROLE_COL={'smart money':'#8b8cff','KOL':'#8b8cff','dev':'#ff9b5e','sniper':'#ff6b6b','bundler':'#ff6b6b','rat trader':'#ff6b6b','arbitrage bot':'#7d90ad','bot':'#7d90ad','whale':'#2bb8ff'};
async function openWallet(addr){
  const el=$('#walBody');CC.wallet=addr;
  el.innerHTML='<button class="back" onclick="history.back()">← Back</button><div class="empty card"><span class="spin"></span> Researching wallet…</div>';
  let d;try{d=await api('/api/wallet/'+encodeURIComponent(addr))}catch(e){el.innerHTML='<button class="back" onclick="history.back()">← Back</button>';needKey(el.appendChild(document.createElement('div')),e.message);return}
  if(CC.wallet!==addr)return;
  if(d.chain&&d.chain!==chainNow()){ST.settings.chain=d.chain;$('#chainSel').value=d.chain;renderChain();CC.disc=null;CC.tape=[]}
  const p=d.profile,a=d.p30,b=d.p7,s=d.style;
  const dist=Object.entries(a.dist),dmax=Math.max(1,...dist.map(x=>x[1]));
  el.innerHTML=`<button class="back" onclick="history.back()">← Back</button>
  <div class="hero"><div><h2>${esc(p.name||'Wallet')} ${p.twitter?`<a class="tag" href="https://x.com/${encodeURIComponent(p.twitter)}" target="_blank" rel="noopener noreferrer">@${esc(p.twitter)} ↗</a>`:''}</h2><div class="addr" onclick="copy('${esc(addr)}')" title="Copy">${esc(addr)} ⧉</div>
   <div class="row" style="gap:6px;margin-top:6px"><span class="tag good">${esc(s.main)}</span><span class="tag">${esc(s.speed)}</span>${p.tags.map(t=>`<span class="tag">${esc(t.replace(/_/g,' '))}</span>`).join('')}${s.dev?`<span class="tag warn">dev · ${s.launched.toLocaleString()} launches</span>`:''}${p.funded_by?`<span class="tag">funded via ${esc(p.funded_by)}</span>`:''}${p.age_days?`<span class="tag">${Math.round(p.age_days)} days old</span>`:''}</div></div>
   <div class="spacer"></div><div class="row"><button class="btn ${d.following?'':'primary'}" id="wFollow">${d.following?'Following ✓':'Follow'}</button><a class="btn" href="https://gmgn.ai/${esc(chainNow())}/address/${encodeURIComponent(addr)}" target="_blank" rel="noopener noreferrer">GMGN ↗</a><a class="btn" href="${scanUrl('account',addr)}" target="_blank" rel="noopener noreferrer">${scanName()} ↗</a></div></div>
  <div class="tiles">${[['Realized P/L 30d',`<span class="${a.realized>=0?'up':'down'}">${a.realized>=0?'+':'−'}${money(Math.abs(a.realized))}</span>`,`ROI ${spct(a.roi)}`],['Win rate 30d',pct(a.winrate),`${a.tokens} tokens`],['Trades 30d',(a.buys+a.sells).toLocaleString(),`${b.buys+b.sells} in 7d`],['Avg hold',a.avg_hold_s?fdur(a.avg_hold_s/60):'—'],['Balance',p.balance?p.balance.toFixed(3):'—'],['Last active',ago(d.last_active)]].map(([k,v,x])=>`<div class="tile"><div class="k">${k}</div><div class="v">${v}</div>${x?`<div class="s">${x}</div>`:''}</div>`).join('')}</div>
  <div class="card gcard" style="margin-bottom:14px"><div class="row" style="justify-content:space-between;align-items:flex-start"><div><h3 style="margin-bottom:4px">Connections</h3><div id="gHead" class="sub">Mapping…</div></div><span class="status" id="gStat"></span></div>
    <div class="gpills" id="gPills"></div>
    <div class="gwrap" id="gWrap"><div class="ghint">scroll to zoom · drag · click a node</div><div class="gpanel" id="gPanel"></div><div class="gtip" id="gTip"></div></div>
    <div class="row" style="justify-content:space-between;margin:16px 0 8px"><h3 style="margin:0">Connected wallets</h3><span class="sub">click to focus</span></div>
    <div class="qscroll" style="max-height:360px;overflow:auto"><table class="tbl" id="gList"></table></div></div>
  <div class="grid2">
    <div class="card"><h3>Results, 30 days</h3><div class="bars" style="margin-top:10px">${dist.map(([k,v])=>`<div class="br"><span>${esc(k)}</span><span class="t"><i style="width:${v/dmax*100}%;background:${k.startsWith('<')||k.startsWith('-')?'var(--coral)':'var(--glow)'}"></i></span><span style="text-align:right">${v}</span></div>`).join('')}</div>
      <div class="row" style="margin-top:14px"><button class="btn small" id="wRun">Copy-trade check (GMGN)</button><span class="sub">Is the record real, is it still working, can you get filled, does it cut losses?</span></div><div id="wOut" style="margin-top:10px"></div></div>
    <div class="card"><h3>Recent trades</h3><div class="tblwrap" style="margin-top:10px;max-height:420px;overflow:auto"><table class="tbl"><tbody>${d.activity.length?d.activity.map(x=>`<tr><td class="sub">${ago(x.ts)}</td><td class="${x.side==='buy'?'up':'down'}">${esc(x.side)}</td><td><a href="#" data-tok="${esc(x.token||'')}"><b>${esc(x.symbol)}</b></a></td><td class="num">${money(x.usd)}</td></tr>`).join(''):'<tr><td><div class="empty">No recent trades.</div></td></tr>'}</tbody></table></div></div>
  </div>`;
  $('#wFollow').onclick=async()=>{try{if(d.following){await api('/api/watchlist/remove',{method:'POST',body:{address:addr}});toast('Unfollowed')}else{await api('/api/watchlist',{method:'POST',body:{address:addr,label:p.name||''}});toast('Following: its trades now show in Smart money')}d.following=!d.following;$('#wFollow').textContent=d.following?'Following ✓':'Follow';$('#wFollow').classList.toggle('primary',!d.following)}catch(e){toast(e.message,true)}};
  $('#wRun').onclick=()=>runJob('wallet',addr,$('#wOut'),reportHTML);
  Graph.init(addr);
}

/* ── connection graph: radial, category-filtered, clustered (d3-force) ── */
const GCATS=[
  ['flow','Fund flow','#36d1e8'],['exchange','Exchanges','#ffb547'],['sibling','Same funder','#ff6a9a'],
  ['smart','Smart money & KOLs','#a98bff'],['trader','Active traders','#ff8a3d'],['dev','Dev & created tokens','#ff5bd0'],['token','Token markets','#3ddc84']];
const GCOL=Object.fromEntries(GCATS.map(c=>[c[0],c[2]]));
const Graph={
  init(addr){
    this.center=addr;this.nodes=new Map();this.links=[];this.expanded=new Set();this.focus=null;
    this.off=new Set();this.open=new Set();this.LIMIT={flow:8,exchange:6,sibling:8,smart:8,trader:8,dev:6,token:10};
    const wrap=$('#gWrap');if(!wrap)return;
    if(typeof d3==='undefined'){wrap.innerHTML='<div class="empty">The graph needs an internet connection to load its drawing library.</div>';return}
    $('#gPills').innerHTML=GCATS.map(([k,l,c])=>`<button class="gpill" data-gc="${k}" style="--c:${c}"><i></i>${l}<span class="n" id="gn-${k}">0</span></button>`).join('');
    $('#gPills').onclick=e=>{const b=e.target.closest('[data-gc]');if(!b)return;const k=b.dataset.gc;this.off.has(k)?this.off.delete(k):this.off.add(k);b.classList.toggle('off',this.off.has(k));this.draw()};
    wrap.querySelectorAll('svg').forEach(s=>s.remove());
    const svg=d3.select(wrap).insert('svg',':first-child');this.svg=svg;
    svg.append('defs').html('<radialGradient id="cglow"><stop offset="0" stop-color="#fff" stop-opacity=".55"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>');
    this.g=svg.append('g');this.rings=this.g.append('g');this.lg=this.g.append('g');this.ng=this.g.append('g');
    this.zoom=d3.zoom().scaleExtent([.3,4]).on('zoom',e=>this.g.attr('transform',e.transform));svg.call(this.zoom).on('dblclick.zoom',null);
    svg.on('click',()=>{this.focus=null;this.highlight();$('#gPanel').classList.remove('on')});
    this.sim=d3.forceSimulation().alphaDecay(.04)
      .force('link',d3.forceLink().id(d=>d.id).distance(l=>l.tier===2?60:90).strength(l=>l.radial?0.04:0.5))
      .force('charge',d3.forceManyBody().strength(d=>d.kind==='center'?-400:-60).distanceMax(260))
      .force('collide',d3.forceCollide().radius(d=>d.r+(d.labelled?26:6)).iterations(2))
      .force('radial',d3.forceRadial(d=>d.ring||0,0,0).strength(d=>d.ring==null?0:.9))
      .on('tick',()=>this.tick());
    this.expand(addr,true);
  },
  async expand(addr,first){
    if(this.expanded.has(addr))return;this.expanded.add(addr);
    $('#gStat').innerHTML='<span class="spin"></span> mapping '+short(addr)+'…';
    let d;try{d=await api('/api/graph/'+encodeURIComponent(addr))}catch(e){$('#gStat').innerHTML=`<span class="down">${esc(e.message)}</span>`;this.expanded.delete(addr);return}
    if(this.center!==CC.wallet)return;
    const parent=this.nodes.get(addr);
    for(const n of d.nodes){const ex=this.nodes.get(n.id);
      if(ex){Object.assign(ex,{info:n.info||ex.info,roles:n.roles||ex.roles,shares_funder:n.shares_funder||ex.shares_funder,exchange:n.exchange||ex.exchange,token:n.token||ex.token});if(n.label&&!/…/.test(n.label))ex.label=n.label}
      else this.nodes.set(n.id,{...n,kind:n.id===this.center?'center':n.type,parent:first?null:addr,x:parent?parent.x+(Math.random()-.5)*40:(Math.random()-.5)*40,y:parent?parent.y+(Math.random()-.5)*40:(Math.random()-.5)*40})}
    const key=l=>`${l.source.id||l.source}|${l.target.id||l.target}|${l.kind}`,have=new Set(this.links.map(key));
    for(const l of d.edges)if(!have.has(key(l))){this.links.push({...l});have.add(key(l))}
    if(first){const s=d.summary,tr=d.edges.filter(e=>e.kind==='sent').reduce((a,e)=>a+(e.count||0),0);
      $('#gHead').innerHTML=`<b>${short(addr)}</b> <span class="sub">${tr.toLocaleString()} transfers · ${s.counterparties} counterparties${s.shared_funder?` · ${s.shared_funder} share its funder`:''}${s.created?` · ${s.created} tokens created`:''}</span>`}
    $('#gStat').textContent='';
    this.classify();this.draw();
    if(first){this.sim.on('end.fit',()=>{this.fit();this.sim.on('end.fit',null)});setTimeout(()=>this.fit(),1200)}
  },
  other(l,id){const s=l.source.id||l.source,t=l.target.id||l.target;return s===id?t:t===id?s:null},
  classify(){
    const C=this.center;
    for(const n of this.nodes.values()){
      const rel=this.links.filter(l=>this.other(l,n.id)!==null&&(l.source.id||l.source)!==(l.target.id||l.target));
      n.weight=rel.reduce((a,l)=>a+(l.count||1)+Math.log10(1+(l.usd||0)),0);
      const i=n.info||{},roles=n.roles||i.roles||[];
      const created=rel.some(l=>l.kind==='created'),bought=rel.some(l=>l.kind==='bought');
      n.cat=n.id===C?'center':n.type==='exchange'||n.exchange?'exchange':n.type==='token'?(created?'dev':'token')
        :n.shares_funder?'sibling':roles.some(r=>r==='smart money'||r==='KOL')?'smart':roles.includes('dev')?'dev'
        :rel.some(l=>l.kind==='funded')||roles.some(r=>/transfer/.test(r))?'flow':i.trades_30d>0?'trader':'flow';
      const fl=this.links.find(l=>l.kind==='funded'&&(l.target.id||l.target)===C&&(l.source.id||l.source)===n.id);
      n.name=n.id===C?'Target wallet':n.cat==='exchange'?(n.exchange||n.label):fl?'Funder':n.cat==='sibling'?'Same funder':n.cat==='token'||n.cat==='dev'&&n.type==='token'?n.label
        :roles.length?(/transfer/.test(roles[0])?'Transfer wallet':roles[0].replace(/^\w/,c=>c.toUpperCase())):n.info&&n.info.name?n.info.name:n.cat==='trader'?'Active trader':'Transfer wallet';
      if(n.info&&n.info.name&&n.cat!=='exchange'&&n.id!==C)n.name=n.info.name;
    }
  },
  visible(){
    const C=this.center,byCat={},vis=new Map(),bubbles=[];
    for(const n of this.nodes.values()){if(n.id===C){vis.set(n.id,n);continue}if(this.off.has(n.cat))continue;(byCat[n.cat]=byCat[n.cat]||[]).push(n)}
    for(const [cat,list] of Object.entries(byCat)){
      list.sort((a,b)=>(b.parent===null)-(a.parent===null)||b.weight-a.weight);
      const lim=this.open.has(cat)?1e9:this.LIMIT[cat]||8;
      list.slice(0,lim).forEach(n=>vis.set(n.id,n));
      if(list.length>lim){const id='bubble-'+cat;const b=this.nodes.get(id)||{id,kind:'bubble',x:0,y:0};b.cat=cat;b.count=list.length-lim;b.name=`${b.count} more`;this.nodes.set(id,b);bubbles.push(b);vis.set(id,b)}
      const el=$('#gn-'+cat);if(el)el.textContent=list.length;
    }
    for(const [k] of GCATS){const el=$('#gn-'+k);if(!el)continue;const n=[...this.nodes.values()].filter(x=>x.cat===k&&x.kind!=='bubble').length;el.textContent=n;el.parentElement.classList.toggle('empty',n===0)}
    const ls=this.links.filter(l=>vis.has(l.source.id||l.source)&&vis.has(l.target.id||l.target));
    for(const b of bubbles)ls.push({source:C,target:b.id,kind:'bubble',bubble:true});
    // rings: important connections inside, the rest outside, clusters in between
    const direct=new Set(ls.filter(l=>[l.source.id||l.source,l.target.id||l.target].includes(C)).map(l=>this.other(l,C)));
    const rankd=[...vis.values()].filter(n=>direct.has(n.id)&&n.kind!=='bubble').sort((a,b)=>b.weight-a.weight);
    const inner=new Set(rankd.filter(n=>['exchange','sibling'].includes(n.cat)||n.name==='Funder').map(n=>n.id).concat(rankd.slice(0,6).map(n=>n.id)));
    for(const n of vis.values()){
      n.ring=n.id===C?0:n.kind==='bubble'?165:inner.has(n.id)?110:direct.has(n.id)?230:null;
      n.labelled=n.id===C||inner.has(n.id)||n.kind==='bubble'||this.expanded.has(n.id);
      n.r=n.id===C?13:n.kind==='bubble'?11+Math.min(9,Math.sqrt(n.count)*1.6):n.labelled?8:4.5+Math.min(3,n.weight/6);
    }
    return {nodes:[...vis.values()],links:ls};
  },
  draw(){
    const {nodes,links}=this.visible(),self=this,tip=$('#gTip'),C=this.center;
    this.rings.selectAll('circle').data([110,230]).join('circle').attr('r',d=>d).attr('fill','none').attr('stroke','#ffffff').attr('stroke-opacity',.035).attr('stroke-dasharray','2 6');
    const L=this.lg.selectAll('line').data(links,l=>`${l.source.id||l.source}|${l.target.id||l.target}|${l.kind}`);
    L.exit().remove();
    L.enter().append('line').merge(L)
      .attr('stroke',l=>l.bubble?'#ffffff':GCOL[(this.nodes.get(this.other(l,C)||(l.target.id||l.target))||{}).cat]||'#5d6b7a')
      .attr('stroke-opacity',l=>l.bubble?.06:.28).attr('stroke-width',l=>l.kind==='funded'?1.6:1)
      .on('mouseenter',(e,l)=>{if(!l.label)return;tip.innerHTML=`<b>${esc(l.label)}</b>${l.ts||l.last?`<br><span class="sub">${new Date((l.ts||l.last)*1000).toLocaleString()}</span>`:''}`;tip.style.display='block'})
      .on('mousemove',e=>{const r=$('#gWrap').getBoundingClientRect();tip.style.left=(e.clientX-r.left+12)+'px';tip.style.top=(e.clientY-r.top+12)+'px'})
      .on('mouseleave',()=>tip.style.display='none');
    const N=this.ng.selectAll('g.gn').data(nodes,n=>n.id);N.exit().remove();
    const E=N.enter().append('g').attr('class','gn').style('cursor','pointer')
      .call(d3.drag().on('start',(e,d)=>{if(!e.active)self.sim.alphaTarget(.2).restart();d.fx=d.x;d.fy=d.y}).on('drag',(e,d)=>{d.fx=e.x;d.fy=e.y}).on('end',(e,d)=>{if(!e.active)self.sim.alphaTarget(0);if(d.id!==C){d.fx=null;d.fy=null}}))
      .on('click',(e,d)=>{e.stopPropagation();if(d.kind==='bubble'){self.open.add(d.cat);self.nodes.delete(d.id);self.draw();return}self.select(d)});
    E.append('circle').attr('class','halo');E.append('circle').attr('class','dot');E.append('text').attr('class','t1');E.append('text').attr('class','t2');E.append('text').attr('class','cnt');
    const M=E.merge(N);
    M.select('.halo').attr('r',d=>d.id===C?40:0).attr('fill','url(#cglow)');
    M.select('.dot').attr('r',d=>d.r).attr('fill',d=>d.id===C?'#ffffff':d.kind==='bubble'?'#3a3a42':GCOL[d.cat]||'#5d6b7a')
      .attr('stroke',d=>d.kind==='bubble'?'#55555e':'#0f0f11').attr('stroke-width',d=>d.kind==='bubble'?1:1.5);
    M.select('.cnt').text(d=>d.kind==='bubble'?d.count:'').attr('dy','.35em').attr('text-anchor','middle');
    M.select('.t1').text(d=>d.labelled?(d.kind==='bubble'?`${d.count} more ${(GCATS.find(c=>c[0]===d.cat)||[0,''])[1].toLowerCase()}`:d.name):'').attr('dy',d=>d.r+15).attr('text-anchor','middle');
    M.select('.t2').text(d=>d.labelled&&d.kind!=='bubble'&&d.kind!=='token'&&d.type!=='token'?short(d.id).replace('…','…'):'').attr('dy',d=>d.r+28).attr('text-anchor','middle');
    this.sim.nodes(nodes);this.sim.force('link').links(links.map(l=>Object.assign(l,{radial:true})));this.sim.alpha(.8).restart();
    const cn=this.nodes.get(C);if(cn){cn.fx=0;cn.fy=0}
    this.renderList();this.highlight();
  },
  tick(){
    this.lg.selectAll('line').attr('x1',l=>l.source.x).attr('y1',l=>l.source.y).attr('x2',l=>l.target.x).attr('y2',l=>l.target.y);
    this.ng.selectAll('g.gn').attr('transform',d=>`translate(${d.x},${d.y})`);
  },
  fit(){const w=$('#gWrap');if(!w)return;const ns=this.sim.nodes();if(!ns.length)return;const W=w.clientWidth,H=w.clientHeight;
    const x0=Math.min(...ns.map(n=>n.x)),x1=Math.max(...ns.map(n=>n.x)),y0=Math.min(...ns.map(n=>n.y)),y1=Math.max(...ns.map(n=>n.y));
    const k=Math.min(1.6,.9/Math.max((x1-x0+120)/W,(y1-y0+120)/H));this.svg.transition().duration(500).call(this.zoom.transform,d3.zoomIdentity.translate(W/2-k*(x0+x1)/2,H/2-k*(y0+y1)/2).scale(k))},
  highlight(){
    const f=this.focus;if(!this.ng)return;
    const near=f?new Set([f,...this.links.map(l=>this.other(l,f)).filter(Boolean)]):null;
    this.ng.selectAll('g.gn').style('opacity',d=>!near||near.has(d.id)||d.id===this.center?1:.18);
    this.lg.selectAll('line').style('opacity',l=>!f||[l.source.id,l.target.id].includes(f)?1:.08);
  },
  focusOn(id){const n=this.nodes.get(id);if(!n)return;this.focus=id;this.highlight();this.select(n);
    const w=$('#gWrap'),k=1.4;this.svg.transition().duration(500).call(this.zoom.transform,d3.zoomIdentity.translate(w.clientWidth/2-k*n.x,w.clientHeight/2-k*n.y).scale(k));
    w.scrollIntoView({behavior:'smooth',block:'center'})},
  renderList(){
    const C=this.center,rows=[...this.nodes.values()].filter(n=>n.id!==C&&n.kind!=='bubble').sort((a,b)=>b.weight-a.weight);
    const what=n=>{const l=this.links.filter(x=>this.other(x,n.id)===C);return l.map(x=>x.label).join(' · ')||'via '+short(n.parent||'')};
    const when=n=>{const t=Math.max(0,...this.links.filter(x=>this.other(x,n.id)!==null).map(x=>x.ts||x.last||0));return t?ago(t):'—'};
    $('#gList').innerHTML=`<thead><tr><th>Connection</th><th>Type</th><th>What happened</th><th class="num">When</th></tr></thead><tbody>`+(rows.length?rows.slice(0,60).map(n=>`<tr class="click" data-gfocus="${esc(n.id)}"><td><b>${esc(n.name||'')}</b><br><span class="sub mono">${n.type==='token'?'token':short(n.id)}</span>${scanIcon(n.type==='token'?'token':'account',n.id)}</td><td><span class="gdot" style="--c:${GCOL[n.cat]||'#5d6b7a'}"></span>${esc((GCATS.find(c=>c[0]===n.cat)||[0,''])[1])}</td><td class="sub" style="white-space:normal">${esc(what(n))}</td><td class="num sub">${when(n)}</td></tr>`).join(''):'<tr><td colspan="4"><div class="empty">No connections found.</div></td></tr>')+'</tbody>';
    $('#gList').onclick=e=>{const r=e.target.closest('[data-gfocus]');if(r)this.focusOn(r.dataset.gfocus)};
  },
  select(n){
    const p=$('#gPanel'),i=n.info||{},rel=this.links.filter(l=>this.other(l,n.id)!==null);
    this.focus=n.id;this.highlight();
    const catName=(GCATS.find(c=>c[0]===n.cat)||[0,n.id===this.center?'Target wallet':''])[1];
    p.innerHTML=`<div class="row" style="justify-content:space-between;margin-bottom:4px"><b style="font-size:15px">${esc(n.name||n.label)}</b><button class="btn small" onclick="Graph.focus=null;Graph.highlight();$('#gPanel').classList.remove('on')">✕</button></div>
      <div class="mono sub" style="word-break:break-all;cursor:pointer" onclick="copy('${esc(n.id)}')">${esc(n.id)} ⧉</div>
      <div style="margin:10px 0"><span class="gdot" style="--c:${n.id===this.center?'#fff':GCOL[n.cat]}"></span>${esc(catName)}</div>
      ${i.address&&!i.error?`<div class="kv" style="margin:8px 0">${[['P/L 30d',(i.realized_30d>=0?'+':'−')+money(Math.abs(i.realized_30d||0))],['Win rate',pct(i.winrate)],['Trades 30d',(i.trades_30d||0).toLocaleString()],['Age',i.age_days?Math.round(i.age_days)+'d':'—'],['Launched',i.created_tokens||0],['Balance',(i.balance||0).toFixed(2)]].map(([k,v])=>`<div>${k}<b>${v}</b></div>`).join('')}</div>
        ${i.funder?`<div class="sub">Funded by ${esc(i.funder_name||short(i.funder))}${i.fund_amount?' · '+i.fund_amount+' native':''}${i.fund_ts?' · '+new Date(i.fund_ts*1000).toLocaleDateString():''}</div>`:''}`:''}
      ${n.token?`<div class="kv" style="margin:8px 0"><div>MC<b>${money(n.token.mcap)}</b></div><div>ATH<b>${n.token.ath_mc?money(n.token.ath_mc):'—'}</b></div><div>Bonded<b>${n.token.bonded?'yes':'no'}</b></div></div>`:''}
      <div style="margin-top:10px">${rel.slice(0,8).map(l=>`<div class="glrow">${esc(l.label||'')}${l.ts||l.last?`<span class="sub">${new Date((l.ts||l.last)*1000).toLocaleString()}</span>`:''}</div>`).join('')}</div>
      <div class="row" style="margin-top:12px;gap:6px">${n.type!=='token'&&n.kind!=='center'&&!this.expanded.has(n.id)&&n.cat!=='exchange'?`<button class="btn small primary" onclick="Graph.expand('${esc(n.id)}')">Expand connections</button>`:''}${n.type==='token'?`<button class="btn small" data-tok="${esc(n.id)}">Research token</button>`:n.cat!=='exchange'&&n.id!==this.center?`<button class="btn small" data-wal="${esc(n.id)}">Open wallet</button>`:''}<a class="btn small" href="${scanUrl(n.type==='token'?'token':'account',n.id)}" target="_blank" rel="noopener noreferrer">${scanName()} ↗</a></div>`;
    p.classList.add('on');
  },
};


/* ── startup (after every view's code is defined) ── */
try{const v=localStorage.getItem('kraken.view');if(v&&$('#v-'+v)&&!['token','wallet'].includes(v))ST.view=v;$('#sRej').checked=localStorage.getItem('kraken.rej')!=='0'}catch(e){}
if(!route())show(ST.view);runBT();
api('/api/setup').then(s=>{if(!s.ready&&!wizSkipped)openWizard(false)}).catch(()=>{});
setInterval(()=>{if(!document.hidden&&!['settings','token','wallet'].includes(ST.view))refresh()},8000);
