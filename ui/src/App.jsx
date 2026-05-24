import { useState, useEffect, useMemo, useRef, useCallback, Component } from "react";

const fmt    = (n,d=0) => n==null||isNaN(n)?"—":Number(n).toLocaleString("en-US",{minimumFractionDigits:d,maximumFractionDigits:d});
const pct    = (n,d=1) => n!=null&&!isNaN(n)?(Number(n)*100).toFixed(d)+"%":"—";
const dollar = n => n!=null&&!isNaN(n)?"$"+fmt(n):"—";
const x2     = n => n!=null&&!isNaN(n)?Number(n).toFixed(3)+"×":"—";
const x1     = n => n!=null&&!isNaN(n)?Number(n).toFixed(2)+"×":"—";
const signed = n => n!=null&&!isNaN(n)?(n>=0?"+":"")+Number(n).toFixed(3):"—";

const C = {
  bg:"#111113", s1:"#18181c", s2:"#202025", s3:"#28282e", s4:"#303038",
  b1:"#333338", b2:"#44444c",
  text:"#efefef", sub:"#9898a8", dim:"#58586a",
  green:"#4caf82",  greenBg:"rgba(76,175,130,.13)",
  amber:"#d4a847",  amberBg:"rgba(212,168,71,.13)",
  red:"#c0453a",    redBg:"rgba(192,69,58,.13)",
  blue:"#5b8dee",   blueBg:"rgba(91,141,238,.13)",
  purple:"#9068d4", purpleBg:"rgba(144,104,212,.13)",
  teal:"#38bdf8",   tealBg:"rgba(56,189,248,.12)",
  gold:"#f0c040",   goldBg:"rgba(240,192,64,.15)",
};

const VERDICTS = {
  elite:            {label:"Elite",      color:C.gold,   bg:C.goldBg},
  strong_buy:       {label:"Strong Buy", color:C.green,  bg:C.greenBg},
  consider:         {label:"Consider",   color:C.amber,  bg:C.amberBg},
  marginal:         {label:"Marginal",   color:C.sub,    bg:C.s3},
  avoid:            {label:"Avoid",      color:C.red,    bg:C.redBg},
  nearly_exhausted: {label:"Near End",   color:C.dim,    bg:C.s3},
  too_new:          {label:"Too New",    color:C.dim,    bg:C.s3},
  no_data:          {label:"No Data",    color:C.dim,    bg:C.s3},
};

function vm(v){ return VERDICTS[v]||VERDICTS.no_data; }
function roiColor(r){ return r>=0.5?C.green:r>=0.25?C.amber:r>=0?C.sub:C.red; }
function ratioColor(r,t=1.0){ return r==null?C.dim:r>=(t+0.02)?C.green:r>=(t-0.02)?C.sub:r>=(t-0.10)?C.amber:C.red; }
function concColor(r){ return ratioColor(r,1.0); }
function concLabel(r){
  if(r==null) return "—";
  if(r>=1.02) return "More concentrated ↑";
  if(r>=0.98) return "Neutral";
  if(r>=0.90) return "Slightly diluted ↓";
  return "Diluted ↓";
}
function entropyLabel(d){
  if(d==null) return "—";
  if(d<-0.05) return "Rapidly concentrating";
  if(d<-0.01) return "Concentrating";
  if(d<0.01)  return "Stable";
  return "Spreading";
}
function momentumColor(m){ return m==null?C.dim:m>0.005?C.green:m>-0.005?C.sub:m>-0.02?C.amber:C.red; }
function momentumLabel(m){ return m==null?"—":m>0.01?"Concentrating fast":m>0.005?"Concentrating":m>-0.005?"Stable":m>-0.01?"Diluting":"Diluting fast"; }
function velDivColor(v){ return v==null?C.dim:v>0.0005?C.green:v>-0.0005?C.sub:C.red; }

function Bar({v=0,color,h=5}){
  return(
    <div style={{background:C.s3,borderRadius:3,height:h,overflow:"hidden"}}>
      <div style={{width:Math.min(100,Math.max(0,(v||0)*100))+"%",height:"100%",background:color,borderRadius:3,transition:"width .4s"}}/>
    </div>
  );
}
function Tip({text,children}){
  const [open,setOpen]=useState(false);
  const ref=useRef(null);
  const [pos,setPos]=useState({top:0,left:0});
  const close=useCallback(e=>{if(ref.current&&!ref.current.contains(e.target))setOpen(false)},[]);
  useEffect(()=>{if(open){document.addEventListener("pointerdown",close);return()=>document.removeEventListener("pointerdown",close)}},[open,close]);
  const show=useCallback(()=>{
    if(!ref.current)return;
    const r=ref.current.getBoundingClientRect();
    const left=Math.max(12,Math.min(r.left+r.width/2,window.innerWidth-12));
    const above=r.top>160;
    setPos({left,top:above?r.top-8:r.bottom+8,above});
    setOpen(true);
  },[]);
  if(!text) return children||null;
  return(
    <span ref={ref} style={{display:"inline-flex",alignItems:"center",cursor:"pointer"}}
      onMouseEnter={show} onMouseLeave={()=>setOpen(false)}
      onClick={e=>{e.stopPropagation();open?setOpen(false):show()}}>
      {children}
      {open&&(
        <span style={{position:"fixed",zIndex:999,
          left:pos.left,top:pos.above?pos.top:undefined,bottom:pos.above?undefined:window.innerHeight-pos.top,
          transform:"translateX(-50%)",
          background:C.s4,color:C.text,fontSize:".65rem",lineHeight:1.45,padding:"8px 12px",
          borderRadius:8,border:`1px solid ${C.b2}`,boxShadow:"0 4px 20px rgba(0,0,0,.45)",
          width:"max-content",maxWidth:"min(280px, calc(100vw - 24px))",pointerEvents:"none",
          animation:"tipIn .15s ease-out"}}>
          {text}
        </span>
      )}
    </span>
  );
}
function Tag({label,color,bg,tip}){
  const inner=<span style={{fontSize:".6rem",fontWeight:600,padding:"2px 8px",borderRadius:4,color,background:bg,whiteSpace:"nowrap"}}>{label}</span>;
  if(!tip) return inner;
  return <Tip text={tip}>{inner}</Tip>;
}
function ScoreRing({score,scoreMax}){
  const max=scoreMax||0.42;
  const p=Math.min(1,Math.max(0,(score||0)/max));
  const r=20,circ=2*Math.PI*r,dash=circ*p;
  const color=p>=0.7?C.green:p>=0.4?C.amber:C.red;
  return(
    <svg width="52" height="52" style={{transform:"rotate(-90deg)",flexShrink:0}}>
      <circle cx="26" cy="26" r={r} fill="none" stroke={C.s3} strokeWidth="4"/>
      <circle cx="26" cy="26" r={r} fill="none" stroke={color} strokeWidth="4"
        strokeDasharray={`${dash} ${circ}`} strokeLinecap="round"/>
      <text x="26" y="26" textAnchor="middle" dominantBaseline="central"
        style={{fill:color,fontSize:"11px",fontWeight:700,transform:"rotate(90deg)",transformOrigin:"26px 26px"}}>
        {Math.round(p*100)}
      </text>
    </svg>
  );
}
function SectionHeader({label,sub}){
  return(
    <div style={{marginBottom:10,marginTop:4}}>
      <div style={{fontSize:".62rem",color:C.dim,textTransform:"uppercase",letterSpacing:"1px"}}>{label}</div>
      {sub&&<div style={{fontSize:".58rem",color:C.dim,marginTop:2}}>{sub}</div>}
    </div>
  );
}
function Tile({label,val,sub,color=C.text,accent,tip}){
  return(
    <div style={{background:C.s2,border:`1px solid ${accent||C.b1}`,borderRadius:10,padding:"10px 12px"}}>
      <div style={{fontSize:".58rem",color:C.dim,marginBottom:4}}>
        {tip?<Tip text={tip}><span>{label}</span></Tip>:label}
      </div>
      <div style={{fontSize:"1rem",fontWeight:700,color,lineHeight:1}}>{val}</div>
      {sub&&<div style={{fontSize:".58rem",color:C.dim,marginTop:4,lineHeight:1.4}}>{sub}</div>}
    </div>
  );
}
function ConcPanel({title,launchP,currP,ratio,printed,remaining,note,asOdds}){
  const cc=concColor(ratio);
  const fP=asOdds
    ? p=>p>0?`1 in ${Math.round(1/p).toLocaleString()}`:"—"
    : p=>pct(p,1);
  const maxP=asOdds?1:Math.max(launchP||0,currP||0,0.0001);
  const barW=asOdds
    ? p=>Math.min(100,(p||0)*2000000)
    : p=>Math.min(100,maxP>0?(p||0)/maxP*100:0);
  return(
    <div style={{background:C.s2,border:`1px solid ${cc}44`,borderRadius:10,padding:14,marginBottom:14}}>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:10}}>
        <div>
          <div style={{fontSize:".7rem",fontWeight:600,color:C.text}}>{title}</div>
          <div style={{fontSize:".58rem",color:C.dim,marginTop:2}}>{remaining} of {printed} prizes remain</div>
        </div>
        <div style={{textAlign:"right",flexShrink:0,marginLeft:8}}>
          <div style={{fontSize:"1rem",fontWeight:700,color:cc}}>{x2(ratio)}</div>
          <div style={{fontSize:".58rem",color:cc}}>{concLabel(ratio)}</div>
        </div>
      </div>
      <div style={{display:"flex",flexDirection:"column",gap:7,marginBottom:8}}>
        {[{label:"At launch",p:launchP,color:C.b2},{label:"Right now",p:currP,color:cc}].map(({label,p,color})=>(
          <div key={label}>
            <div style={{display:"flex",justifyContent:"space-between",marginBottom:3}}>
              <span style={{fontSize:".6rem",color:C.sub}}>{label}</span>
              <span style={{fontSize:".7rem",fontWeight:600,color}}>{fP(p)}</span>
            </div>
            <div style={{background:C.s3,borderRadius:3,height:7,overflow:"hidden"}}>
              <div style={{width:barW(p)+"%",height:"100%",background:color,borderRadius:3}}/>
            </div>
          </div>
        ))}
      </div>
      <div style={{fontSize:".62rem",fontWeight:600,color:cc,marginBottom:note?6:0}}>
        {remaining===0?"⚠ All prizes in this tier claimed"
         :ratio>=1?`▲ ${((ratio-1)*100).toFixed(1)}% more likely than at launch`
         :`▼ ${((1-ratio)*100).toFixed(1)}% less likely than at launch`}
      </div>
      {note&&<div style={{fontSize:".6rem",color:C.sub,lineHeight:1.5}}>{note}</div>}
    </div>
  );
}

// ── GameCard ──────────────────────────────────────────────────────────────────
function GameCard({g,rank,onClick,scoreMax}){
  const v=vm(g.verdict);
  const actionable=["elite","strong_buy","consider"].includes(g.verdict);
  const rc=g.roi_on_max_loss!=null?roiColor(g.roi_on_max_loss):C.dim;
  const cc=concColor(g.composite_conc!=null?g.composite_conc:g.concentration_ratio);
  const wrc=ratioColor(g.win_rate_ratio,1.0);
  const evgwc=ratioColor(g.ev_given_win_ratio,1.0);

  return(
    <div style={{background:C.s1,border:`1px solid ${C.b1}`,borderRadius:12,padding:"14px 16px",
        opacity:["too_new","no_data"].includes(g.verdict)?.4:1}}>

      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:8}}>
        <div style={{display:"flex",alignItems:"center",gap:8}}>
          <Tag label={v.label} color={v.color} bg={v.bg}/>
          {rank<=10&&actionable&&<span style={{fontSize:".6rem",color:C.dim}}>#{rank}</span>}
        </div>
        {actionable&&g.adj_prof_score!=null&&<ScoreRing score={g.adj_prof_score} scoreMax={scoreMax}/>}
      </div>

      <div style={{fontSize:"1rem",fontWeight:600,color:C.text,marginBottom:3}}>{g.game_name}</div>
      <div style={{fontSize:".63rem",color:C.dim,display:"flex",gap:10,flexWrap:"wrap",marginBottom:actionable?12:4}}>
        <span>{dollar(g.ticket_price)}/ticket</span>
        <span>{pct(g.maturity,0)} sold</span>
        <span>{g.pack_size}pk · {dollar(g.pack_cost)}</span>
        {g.close_date&&<span style={{color:C.red}}>⚠ {g.close_date}</span>}
      </div>

      {!actionable?(
        <div style={{fontSize:".68rem",color:C.dim}}>
          {g.verdict==="avoid"?"EV below guarantee floor.":"Insufficient data for scoring."}
        </div>
      ):(
        <>
          {/* Primary 3 */}
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:7,marginBottom:10}}>
            {[
              {label:"ROI on Risk",  val:pct(g.roi_on_max_loss,0),   color:rc,
               tip:"Expected return above guarantee as % of max possible loss per pack"},
              {label:"Max Loss",     val:dollar(g.max_loss_per_pack), color:C.red,
               tip:"Worst-case loss per pack: pack cost minus guarantee"},
              {label:"EV / Pack",    val:dollar(g.ev_per_pack),       color:C.green,
               tip:"Expected dollar value of remaining prizes in one pack"},
            ].map(({label,val,color,tip})=>(
              <div key={label} style={{background:C.s3,borderRadius:8,padding:"8px 9px"}}>
                <div style={{fontSize:".55rem",color:C.dim,marginBottom:2}}>
                  <Tip text={tip}><span>{label}</span></Tip>
                </div>
                <div style={{fontSize:".9rem",fontWeight:700,color}}>{val}</div>
              </div>
            ))}
          </div>

          {/* Signal row */}
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr 1fr",gap:7,marginBottom:10}}>
            {[
              {label:"Win Rate",  val:x1(g.win_rate_ratio),     color:wrc,  sub:"vs launch",
               tip:"Current win rate vs launch. >1.0× means more winners per remaining ticket"},
              {label:"EV if Win", val:x1(g.ev_given_win_ratio), color:evgwc,sub:"vs launch",
               tip:"Average winning ticket value vs launch. >1.0× means bigger prizes remain"},
              {label:"Conc.",     val:g.n_meaningful_tiers>0?x1(g.composite_conc):"N/A", color:cc, sub:"vs launch",
               tip:"Scarcity-weighted concentration of rare prizes. >1.0× means rare prizes are retaining better than average"},
              {label:"Velocity",  val:g.velocity_divergence!=null?signed(g.velocity_divergence):"—", color:velDivColor(g.velocity_divergence), sub:"base−top",
               tip:"Claim rate gap between common and rare tiers. Positive means common prizes are draining faster, so concentration is actively improving"},
            ].map(({label,val,color,sub,tip})=>(
              <div key={label} style={{background:C.s3,borderRadius:8,padding:"8px 9px"}}>
                <div style={{fontSize:".55rem",color:C.dim,marginBottom:2}}>
                  <Tip text={tip}><span>{label}</span></Tip>
                </div>
                <div style={{fontSize:".9rem",fontWeight:700,color}}>{val}</div>
                <div style={{fontSize:".52rem",color:C.dim}}>{sub}</div>
              </div>
            ))}
          </div>

          {/* Scenario bar */}
          {g.scenario_p10!=null&&(
            <div style={{background:C.s3,borderRadius:8,padding:"9px 11px",marginBottom:10}}>
              <div style={{fontSize:".58rem",color:C.sub,marginBottom:7}}>
                <Tip text="20,000 simulated pack draws. Light band = P10 to P90 range, dark band = P25 to P75, blue line = median, amber line = guarantee floor">
                  <span>Pack return scenarios</span>
                </Tip>
                {" · floor: "}{dollar(g.guarantee_per_pack)}
              </div>
              <div style={{position:"relative",height:16,borderRadius:3,overflow:"hidden",background:C.s2}}>
                {[
                  {l:g.scenario_p10,r:g.scenario_p90,color:"rgba(91,141,238,.2)"},
                  {l:g.scenario_p25,r:g.scenario_p75,color:"rgba(91,141,238,.35)"},
                ].map(({l,r,color},i)=>{
                  const max=g.scenario_p90*1.05;
                  return <div key={i} style={{position:"absolute",top:0,bottom:0,
                    left:(l/max*100)+"%",width:((r-l)/max*100)+"%",background:color,borderRadius:3}}/>;
                })}
                <div style={{position:"absolute",top:0,bottom:0,width:3,background:C.blue,borderRadius:2,
                  left:(g.scenario_p50/(g.scenario_p90*1.05)*100)+"%"}}/>
                <div style={{position:"absolute",top:0,bottom:0,width:2,background:C.amber,borderRadius:2,
                  left:(g.guarantee_per_pack/(g.scenario_p90*1.05)*100)+"%"}}/>
              </div>
              <div style={{display:"flex",justifyContent:"space-between",marginTop:5,fontSize:".56rem",color:C.dim}}>
                <Tip text="Worst 10% of simulated packs returned this or less"><span>P10: {dollar(g.scenario_p10)}</span></Tip>
                <Tip text="Median: half of simulated packs returned more, half less"><span style={{color:C.blue}}>P50: {dollar(g.scenario_p50)}</span></Tip>
                <Tip text="Best 10% of simulated packs returned this or more"><span>P90: {dollar(g.scenario_p90)}</span></Tip>
              </div>
            </div>
          )}

          {/* Confidence strips */}
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:7,marginBottom:10}}>
            {[
              {label:"Maturity confidence",v:g.maturity_confidence||0,color:C.blue,
               tip:"How reliable the analysis is based on sell-through. Peaks around 65% sold. Too new or nearly exhausted = low confidence"},
              {label:"Floor protection",   v:g.downside_protection||0, color:C.amber,
               tip:"Guarantee as a fraction of pack cost. Higher = less money at risk per pack"},
            ].map(({label,v,color,tip})=>(
              <div key={label}>
                <div style={{display:"flex",justifyContent:"space-between",marginBottom:3}}>
                  <span style={{fontSize:".55rem",color:C.dim}}>
                    <Tip text={tip}><span>{label}</span></Tip>
                  </span>
                  <span style={{fontSize:".55rem",color:C.sub}}>{pct(v,0)}</span>
                </div>
                <Bar v={v} color={color} h={4}/>
              </div>
            ))}
          </div>

          <div style={{display:"flex",gap:5,flexWrap:"wrap"}}>
            <Tag label={`Guar. ${dollar(g.guarantee_per_pack)}`} color={C.amber} bg={C.amberBg}
              tip="Minimum guaranteed payout per pack. This is your loss floor"/>
            {g.jp_remaining===0&&<Tag label="Jackpot Gone" color={C.red} bg={C.redBg}
              tip="All jackpot prizes have been claimed"/>}
            {g.jp_remaining>0&&(g.jp_conc_ratio||0)>=1.02&&
              <Tag label={`JP ↑${x1(g.jp_conc_ratio)}`} color={C.green} bg={C.greenBg}
                tip="Jackpot is retaining better than average, so your odds of hitting it have improved relative to launch"/>}
            {(g.win_rate_ratio||0)>=1.0&&
              <Tag label="Win Rate ↑" color={C.teal} bg={C.tealBg}
                tip="More winners per remaining ticket than at launch"/>}
            {(g.ev_given_win_ratio||0)>=1.0&&
              <Tag label="EV|Win ↑" color={C.purple} bg={C.purpleBg}
                tip="Average winning ticket is worth more than at launch"/>}
            {g.momentum!=null&&g.momentum>0.005&&
              <Tag label="Momentum ↑" color={C.teal} bg={C.tealBg}
                tip="Concentration is actively increasing compared to the prior snapshot"/>}
          </div>
          <button onClick={e=>{e.stopPropagation();onClick(g)}}
            style={{width:"100%",marginTop:10,padding:"8px 0",background:C.s3,
              border:`1px solid ${C.b1}`,borderRadius:8,color:C.sub,
              fontFamily:"'Poppins',sans-serif",fontSize:".7rem",fontWeight:500,
              cursor:"pointer",transition:"background .15s,color .15s"}}
            onMouseEnter={e=>{e.currentTarget.style.background=C.s4;e.currentTarget.style.color=C.text}}
            onMouseLeave={e=>{e.currentTarget.style.background=C.s3;e.currentTarget.style.color=C.sub}}>
            View Details →
          </button>
        </>
      )}
    </div>
  );
}

// ── Detail view ───────────────────────────────────────────────────────────────
function Detail({g,onClose,scoreMax}){
  const v=vm(g.verdict);
  const rc=roiColor(g.roi_on_max_loss||0);
  const cc=concColor(g.composite_conc!=null?g.composite_conc:g.concentration_ratio);
  const wrc=ratioColor(g.win_rate_ratio,1.0);
  const evgwc=ratioColor(g.ev_given_win_ratio,1.0);

  return(
    <div style={{position:"fixed",inset:0,background:C.bg,zIndex:100,overflowY:"auto",WebkitOverflowScrolling:"touch"}}>
      <div style={{position:"sticky",top:0,background:C.s1,borderBottom:`1px solid ${C.b1}`,
        padding:"12px 16px",display:"flex",alignItems:"center",gap:10,zIndex:10}}>
        <button onClick={onClose} style={{background:C.s2,border:`1px solid ${C.b1}`,color:C.sub,
          width:34,height:34,borderRadius:8,cursor:"pointer",fontSize:"1.1rem",flexShrink:0,
          display:"flex",alignItems:"center",justifyContent:"center"}}>←</button>
        <div style={{flex:1,minWidth:0}}>
          <div style={{fontSize:".9rem",fontWeight:600,color:C.text,
            whiteSpace:"nowrap",overflow:"hidden",textOverflow:"ellipsis"}}>{g.game_name}</div>
          <div style={{fontSize:".6rem",color:C.dim}}>#{g.game_number} · {dollar(g.ticket_price)}/ticket · {pct(g.maturity,0)} sold</div>
        </div>
        <div style={{display:"flex",alignItems:"center",gap:8,flexShrink:0}}>
          <Tag label={v.label} color={v.color} bg={v.bg}/>
          {g.adj_prof_score!=null&&<ScoreRing score={g.adj_prof_score} scoreMax={scoreMax}/>}
        </div>
      </div>

      <div className="detail-inner" style={{padding:"14px 16px 48px"}}>

        {/* Score breakdown */}
        {g.adj_prof_score!=null&&(
          <>
            <SectionHeader label="Profitability Score" sub="ROI × Maturity Confidence × Floor Protection × Signal Multipliers"/>
            <div style={{background:C.s2,border:`1px solid ${C.b1}`,borderRadius:10,padding:14,marginBottom:20}}>
              <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:10,marginBottom:12}}>
                {[
                  {label:"ROI on Max Loss",     val:pct(g.roi_on_max_loss,0),     color:rc,    note:"Return on at-risk capital"},
                  {label:"Maturity Confidence", val:pct(g.maturity_confidence,0), color:C.blue,note:`${pct(g.maturity,0)} sold, peaks ~65%`},
                  {label:"Floor Protection",    val:pct(g.downside_protection,0), color:C.amber,note:`${dollar(g.guarantee_per_pack)} of ${dollar(g.pack_cost)}`},
                ].map(({label,val,color,note})=>(
                  <div key={label}>
                    <div style={{fontSize:".58rem",color:C.dim,marginBottom:4}}>{label}</div>
                    <div style={{fontSize:"1rem",fontWeight:700,color,marginBottom:4}}>{val}</div>
                    <Bar v={parseFloat(val)/100||0} color={color} h={3}/>
                    <div style={{fontSize:".55rem",color:C.dim,marginTop:4}}>{note}</div>
                  </div>
                ))}
              </div>
              <div style={{borderTop:`1px solid ${C.b1}`,paddingTop:10,fontSize:".65rem",color:C.sub,lineHeight:1.7}}>
                Base: <strong>{g.prof_score?.toFixed(4)}</strong>
                {" × "}Conc: <strong style={{color:cc}}>{g.conc_mult?.toFixed(3)}×</strong>
                {" × "}JP: <strong style={{color:concColor(g.jp_conc_ratio)}}>{g.jp_mult?.toFixed(3)}×</strong>
                {" × "}WR: <strong style={{color:wrc}}>{g.wr_mult?.toFixed(3)}×</strong>
                {" × "}EV|Win: <strong style={{color:evgwc}}>{g.evgw_mult?.toFixed(3)}×</strong>
                {" = "}<strong style={{color:C.green}}>{g.adj_prof_score?.toFixed(4)}</strong>
                {" ("}{(g.adj_prof_score/scoreMax*100).toFixed(1)}{"% of max)"}
              </div>
            </div>
          </>
        )}

        {/* Pool quality */}
        <SectionHeader label="Pool Quality Signals" sub="How the remaining prize pool has evolved since launch"/>
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10,marginBottom:10}}>
          <Tile label="Win Rate Now"      val={pct(g.current_win_rate,2)}        sub={`Was ${pct(g.launch_win_rate,2)} at launch`} color={wrc} accent={wrc+"33"}
            tip="Percentage of remaining tickets that are winners"/>
          <Tile label="Win Rate Drift"    val={x2(g.win_rate_ratio)}             sub={g.win_rate_ratio>=1?"More winners/ticket":"Fewer winners/ticket"} color={wrc} accent={wrc+"33"}
            tip="Current win rate divided by launch win rate. >1.0× means more winners per remaining ticket than at launch"/>
          <Tile label="Avg Win Now"       val={dollar(g.ev_given_win_current)}   sub={`Was ${dollar(g.ev_given_win_launch)} at launch`} color={evgwc} accent={evgwc+"33"}
            tip="Average dollar value of a winning ticket right now"/>
          <Tile label="EV|Win Drift"      val={x2(g.ev_given_win_ratio)}         sub={g.ev_given_win_ratio>=1?"Pool enriching":"Pool shrinking"} color={evgwc} accent={evgwc+"33"}
            tip="Current avg win value divided by launch value. >1.0× means remaining wins are worth more on average"/>
        </div>
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10,marginBottom:20}}>
          <Tile label="Entropy Δ"         val={signed(g.entropy_delta)}          sub={entropyLabel(g.entropy_delta)} color={g.entropy_delta<-0.01?C.green:g.entropy_delta>0.01?C.amber:C.sub}
            tip="Change in prize distribution entropy. Negative means prizes are concentrating into fewer tiers"/>
          <Tile label="Expected Winners"  val={`${g.expected_winners_current?.toFixed(1)||"—"}/pack`} sub={`Was ${g.expected_winners_launch?.toFixed(1)||"—"} at launch`}
            tip="How many winning tickets you'd expect in a single pack based on current odds"/>
        </div>

        {/* Velocity & Momentum */}
        {g.days_since_prior!=null&&(
          <>
            <SectionHeader label="Velocity & Momentum" sub={`Comparing to ${g.days_since_prior}-day prior snapshot`}/>
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10,marginBottom:10}}>
              <Tile label="Momentum" val={signed(g.momentum)} sub={momentumLabel(g.momentum)}
                color={momentumColor(g.momentum)} accent={momentumColor(g.momentum)+"33"}
                tip="Change in composite concentration since prior snapshot. Positive means concentration is actively improving"/>
              <Tile label="Win Rate Velocity" val={g.win_rate_velocity!=null?`${signed(g.win_rate_velocity)}/day`:"—"}
                sub={g.win_rate_velocity>0?"Pool enriching faster":"Pool enriching slower"}
                color={g.win_rate_velocity>0?C.green:g.win_rate_velocity<0?C.amber:C.sub}
                tip="Daily change in win rate ratio. Positive means each remaining ticket is becoming more likely to win"/>
              <Tile label="Base Tier Velocity" val={g.claim_velocity_base!=null?pct(g.claim_velocity_base,3):"—"}
                sub="Common tiers drain rate/day"
                tip="Average daily claim rate across common/uncommon prize tiers, as a fraction of total printed"/>
              <Tile label="Top Tier Velocity" val={g.claim_velocity_top!=null?pct(g.claim_velocity_top,3):"—"}
                sub="Scarce+ tiers drain rate/day"
                tip="Average daily claim rate across scarce, rare, and ultra-rare tiers. Lower than base = concentration improving"/>
            </div>
            <div style={{marginBottom:20}}>
              <Tile label="Velocity Divergence" val={g.velocity_divergence!=null?signed(g.velocity_divergence):"—"}
                sub={g.velocity_divergence>0?"Base draining faster than top, concentration improving"
                  :g.velocity_divergence<0?"Top draining faster, concentration eroding":"Even drain rates"}
                color={velDivColor(g.velocity_divergence)} accent={velDivColor(g.velocity_divergence)+"33"}
                tip="Gap between base and top tier drain rates. Positive means common prizes are being claimed faster than rare ones, so the pool is concentrating"/>
            </div>
          </>
        )}

        {/* Pack analytics */}
        {g.pack_cost&&(
          <>
            <SectionHeader label="Pack Analytics"/>
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10,marginBottom:10}}>
              <Tile label="Pack Size"    val={`${g.pack_size} tickets`} sub={`${dollar(g.ticket_price)} each`}
                tip="Number of consecutive tickets in a pack"/>
              <Tile label="Pack Cost"   val={dollar(g.pack_cost)}
                tip="Total cost to buy one full pack"/>
              <Tile label="Guarantee"  val={dollar(g.guarantee_per_pack)} sub="Minimum return" color={C.amber} accent={C.amber+"44"}
                tip="Minimum guaranteed payout per pack. This is your loss floor"/>
              <Tile label="Max Loss"   val={dollar(g.max_loss_per_pack)}  sub="True risk" color={C.red} accent={C.red+"44"}
                tip="Pack cost minus guarantee. The most you can actually lose"/>
              <Tile label="EV Anchor"  val={pct(g.sell_through,1)} sub={`${dollar(g.prize_levels?.[0]?.amount)} tier sell-thru`} color={C.blue}
                tip="Estimated % of tickets sold, based on the smallest prize tier's claim rate"/>
              <Tile label="EV / Pack"  val={dollar(g.ev_per_pack)} color={g.ev_per_pack>g.guarantee_per_pack?C.green:C.amber}
                tip="Expected value of remaining prizes across one pack of tickets"/>
              <Tile label="Above Guarantee" val={dollar(g.expected_above_guarantee)} color={g.expected_above_guarantee>0?C.green:C.red} accent={g.expected_above_guarantee>0?C.green+"33":C.red+"33"}
                tip="How much EV per pack exceeds the guarantee floor"/>
              <Tile label="ROI on Max Loss" val={pct(g.roi_on_max_loss,0)} color={rc} accent={rc+"33"}
                tip="Above-guarantee value as a percentage of max loss. Your risk-adjusted return"/>
            </div>
          </>
        )}

        {/* Scenarios */}
        {g.scenario_p50!=null&&(
          <>
            <SectionHeader label="Pack Return Scenarios" sub="Monte Carlo simulation, 20,000 simulated packs"/>
            <div style={{background:C.s2,border:`1px solid ${C.b1}`,borderRadius:10,padding:14,marginBottom:14}}>
              <div style={{position:"relative",height:28,borderRadius:4,overflow:"hidden",background:C.s3,marginBottom:10}}>
                {[
                  {l:g.scenario_p10,r:g.scenario_p90,color:"rgba(91,141,238,.18)"},
                  {l:g.scenario_p25,r:g.scenario_p75,color:"rgba(91,141,238,.32)"},
                ].map(({l,r,color},i)=>{
                  const max=g.scenario_p90*1.08;
                  return <div key={i} style={{position:"absolute",top:0,bottom:0,
                    left:(l/max*100)+"%",width:((r-l)/max*100)+"%",background:color,borderRadius:3}}/>;
                })}
                <div style={{position:"absolute",top:0,bottom:0,width:3,background:C.blue,
                  left:(g.scenario_p50/(g.scenario_p90*1.08)*100)+"%"}}/>
                <div style={{position:"absolute",top:0,bottom:0,width:2,background:C.amber,
                  left:(g.guarantee_per_pack/(g.scenario_p90*1.08)*100)+"%"}}/>
                <div style={{position:"absolute",top:0,bottom:0,width:2,background:C.red,opacity:.5,
                  left:(g.pack_cost/(g.scenario_p90*1.08)*100)+"%"}}/>
              </div>
              <div style={{display:"grid",gridTemplateColumns:"repeat(5,1fr)",gap:6,marginBottom:12}}>
                {[
                  {label:"P10",val:g.scenario_p10,color:C.red},
                  {label:"P25",val:g.scenario_p25,color:C.sub},
                  {label:"P50",val:g.scenario_p50,color:C.blue},
                  {label:"P75",val:g.scenario_p75,color:C.sub},
                  {label:"P90",val:g.scenario_p90,color:C.green},
                ].map(({label,val,color})=>(
                  <div key={label}>
                    <div style={{fontSize:".55rem",color:C.dim}}>{label}</div>
                    <div style={{fontSize:".8rem",fontWeight:700,color}}>{dollar(val)}</div>
                  </div>
                ))}
              </div>
              <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8,borderTop:`1px solid ${C.b1}`,paddingTop:10}}>
                <div>
                  <div style={{fontSize:".58rem",color:C.dim,marginBottom:3}}>
                    <Tip text="Guarantee ÷ worst-case simulated return (P10). Above 1.5× means the floor catches most bad outcomes"><span>Guarantee adequacy</span></Tip>
                  </div>
                  <div style={{fontSize:".9rem",fontWeight:700,color:g.guarantee_adequacy>=2?C.green:g.guarantee_adequacy>=1.5?C.amber:C.sub}}>
                    {x1(g.guarantee_adequacy)}
                  </div>
                  <div style={{fontSize:".55rem",color:C.dim,marginTop:2}}>Guarantee vs P10. Above 1.5× is strong</div>
                </div>
                <div>
                  <div style={{fontSize:".58rem",color:C.dim,marginBottom:3}}>
                    <Tip text="Spread between best and worst simulated outcomes. Lower = more predictable returns"><span>Variance (P90/P10)</span></Tip>
                  </div>
                  <div style={{fontSize:".9rem",fontWeight:700,color:g.variance_score<=3?C.green:g.variance_score<=5?C.amber:C.sub}}>
                    {x1(g.variance_score)}
                  </div>
                  <div style={{fontSize:".55rem",color:C.dim,marginTop:2}}>Lower = more predictable</div>
                </div>
              </div>
            </div>
          </>
        )}

        {/* Composite concentration */}
        <SectionHeader label={`Scarcity-Weighted Concentration`} sub={`${g.n_meaningful_tiers} meaningful tier${g.n_meaningful_tiers!==1?"s":""} (scarce/rare/ultra-rare)`}/>
        {g.n_meaningful_tiers>0?(
          <ConcPanel
            title={`Composite across ${g.n_meaningful_tiers} tier${g.n_meaningful_tiers!==1?"s":""}`}
            launchP={g.p_top_launch_pack} currP={g.p_top_curr_pack}
            ratio={g.composite_conc} printed={g.top_bucket_printed} remaining={g.top_bucket_remaining}
            note={`Ultra-rare prizes weighted ~4× more than scarce. Ratio above 1.0× = big prizes concentrating.`}/>
        ):(
          <div style={{background:C.s2,border:`1px solid ${C.b1}`,borderRadius:10,padding:14,marginBottom:14}}>
            <div style={{fontSize:".7rem",color:C.dim}}>No scarce or rarer prize tiers. All prizes are high-volume, so concentration signal does not apply.</div>
          </div>
        )}

        {/* Jackpot concentration */}
        <SectionHeader label={`Jackpot Concentration (${dollar(g.jp_amount)})`}/>
        <ConcPanel
          title={`${g.jp_remaining} of ${g.jp_printed} jackpot${g.jp_printed!==1?"s":""} remain`}
          launchP={g.p_jp_launch_pack} currP={g.p_jp_curr_pack}
          ratio={g.jp_conc_ratio} printed={g.jp_printed} remaining={g.jp_remaining}
          asOdds={true}
          note={g.jp_remaining===0?"All jackpots claimed."
            :g.jp_conc_ratio>=1.0?"Jackpot more concentrated than at launch. Odds have improved."
            :"Jackpot draining faster than overall pool."}/>

        {/* Prize table */}
        <SectionHeader label="Prize Level Detail" sub="Deviation = this tier's retention minus overall retention"/>
        <div style={{background:C.s2,border:`1px solid ${C.b1}`,borderRadius:10,overflow:"hidden",marginBottom:20}}>
          {(g.prize_levels||[]).slice().reverse().map((pl,i)=>{
            const isAnchor=i===(g.prize_levels||[]).length-1;
            const isJP=pl.is_jackpot;
            const isM=pl.is_meaningful;
            const dc=pl.deviation>0.015?C.green:pl.deviation<-0.015?C.red:C.sub;
            const rowBg=isJP?C.greenBg:isM?"rgba(76,175,130,.05)":isAnchor?C.blueBg:"transparent";
            const tierColors={ultra_rare:{c:C.green},rare:{c:C.red},scarce:{c:C.amber},uncommon:{c:C.sub},common:{c:C.dim}};
            const tc=(tierColors[pl.tier]||{c:C.dim}).c;
            return(
              <div key={i} style={{background:rowBg,borderBottom:`1px solid ${C.b1}`,padding:"10px 14px",opacity:pl.remaining===0?.3:1}}>
                <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:6}}>
                  <div style={{display:"flex",alignItems:"center",gap:6,flexWrap:"wrap"}}>
                    <span style={{fontSize:".88rem",fontWeight:700,color:isJP?C.green:isM?tc:isAnchor?C.blue:C.amber}}>{dollar(pl.amount)}</span>
                    {isJP&&<Tag label="jackpot" color={C.green} bg={C.greenBg}/>}
                    {pl.tier==="ultra_rare"&&!isJP&&<Tag label="💎 ultra rare" color={C.green} bg={C.greenBg}/>}
                    {pl.tier==="rare"&&<Tag label="🔴 rare" color={C.red} bg={C.redBg}/>}
                    {pl.tier==="scarce"&&<Tag label="🟠 scarce" color={C.amber} bg={C.amberBg}/>}
                    {isAnchor&&<Tag label="EV anchor" color={C.blue} bg={C.blueBg}/>}
                  </div>
                  <div style={{textAlign:"right"}}>
                    <span style={{fontSize:".72rem",fontWeight:600,color:dc}}>
                      {pl.deviation>=0?"+":""}{(pl.deviation*100).toFixed(2)}pp
                    </span>
                    <div style={{fontSize:".55rem",color:C.dim}}>vs overall</div>
                  </div>
                </div>
                <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr 1fr 1fr",gap:4}}>
                  {[
                    {label:"Printed",   val:fmt(pl.total)},
                    {label:"Remaining", val:fmt(pl.remaining)},
                    {label:"Retention", val:pct(pl.retention)},
                    {label:"1-in",      val:pl.one_in>0?fmt(pl.one_in):"—"},
                    {label:"Vel/day",   val:pl.claim_velocity!=null?pct(pl.claim_velocity,3):"—"},
                  ].map(({label,val})=>(
                    <div key={label}>
                      <div style={{fontSize:".52rem",color:C.dim}}>{label}</div>
                      <div style={{fontSize:".7rem",color:C.sub,fontWeight:500}}>{val}</div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>

      </div>
    </div>
  );
}

// ── Guide ────────────────────────────────────────────────────────────────────
const GUIDE_SECTIONS = [
  {
    title:"How This Works",
    color:C.blue,
    entries:[
      {term:"The Core Idea",
       def:"Texas Lottery scratch-off packs come with a guaranteed minimum payout. This transforms a pure gamble into a bounded-loss proposition. We track every game's remaining prize pool daily and compute which packs offer the best risk-adjusted expected value above that guarantee floor."},
      {term:"Sell-Through Estimation",
       def:"We estimate how many tickets have been sold using the smallest prize tier's claim rate. Small prizes get cashed almost immediately, so their claim rate is the best proxy for actual tickets sold. This is more accurate than using overall maturity, which over-counts remaining tickets when big prizes have already been hit."},
    ],
  },
  {
    title:"Card Metrics",
    color:C.green,
    entries:[
      {term:"ROI on Risk",
       def:"Expected return above the guarantee, expressed as a percentage of your maximum possible loss (pack cost minus guarantee). A 60% ROI means for every dollar you could lose, you expect to get back $0.60 in EV above the floor."},
      {term:"Max Loss",
       def:"The most you can actually lose on one pack: pack cost minus the guaranteed payout. This is your true risk, not the pack price."},
      {term:"EV / Pack",
       def:"The expected dollar value of remaining prizes across one pack of tickets. Calculated from the current remaining prize pool divided by estimated remaining tickets, multiplied by pack size."},
      {term:"Win Rate",
       def:"Current win rate divided by launch win rate. Above 1.0× means there are more winners per remaining ticket than when the game launched, so the pool is enriching."},
      {term:"EV if Win",
       def:"Average value of a winning ticket now vs at launch. Above 1.0× means the remaining wins are worth more on average because larger prizes are retaining disproportionately."},
      {term:"Concentration",
       def:"Scarcity-weighted measure of how well rare prizes are retaining compared to the overall pool. Ultra-rare prizes get ~16× the weight of scarce prizes. Above 1.0× means rare prizes are still in the pool at a higher rate than average, tilting the pool toward bigger wins."},
      {term:"Velocity",
       def:"The gap between base-tier and top-tier claim rates per day. Positive means common prizes are being claimed faster than rare ones, so concentration is actively improving right now, not just high from a past state."},
    ],
  },
  {
    title:"Scenario Bar",
    color:C.blue,
    entries:[
      {term:"How It's Built",
       def:"We simulate 20,000 pack purchases using the current prize pool odds. Each simulation randomly draws prizes at current probabilities to produce a total pack return. The distribution of those 20,000 outcomes gives us the percentile bands."},
      {term:"P10 / P50 / P90",
       def:"P10 is the 10th percentile: only 10% of simulated packs returned less than this. P50 is the median outcome. P90 is the 90th percentile: only 10% returned more. The light band spans P10 to P90; the dark band spans P25 to P75."},
      {term:"Blue Line (Median)",
       def:"The vertical blue line marks the median (P50) pack return, your most likely outcome."},
      {term:"Amber Line (Guarantee)",
       def:"The amber line marks the guaranteed minimum payout. When it sits well below P10, even bad luck beats the floor."},
    ],
  },
  {
    title:"Confidence Indicators",
    color:C.amber,
    entries:[
      {term:"Maturity Confidence",
       def:"How much we trust the analysis based on sell-through rate. Uses a bell curve that peaks around 65% sold. Too new (<10% sold) means insufficient data; nearly exhausted (>92%) means the pool is depleted and scores are unreliable."},
      {term:"Floor Protection",
       def:"Guarantee as a fraction of pack cost. A $100 pack with an $85 guarantee has 85% floor protection, meaning you can only lose $15. Higher protection means less capital at risk."},
    ],
  },
  {
    title:"Tags",
    color:C.green,
    entries:[
      {term:"Guar. $XXX",
       def:"The minimum guaranteed payout for one pack. This is your loss floor, the worst possible outcome."},
      {term:"JP ↑X.XX×",
       def:"The jackpot is retaining better than average. The number shows how concentrated jackpot odds are relative to launch. Above 1.0× means your per-ticket jackpot odds have improved."},
      {term:"Win Rate ↑",
       def:"Current win rate exceeds launch win rate. More winners per remaining ticket than when the game started."},
      {term:"EV|Win ↑",
       def:"Average winning ticket value exceeds launch. Remaining wins are worth more on average."},
      {term:"Momentum ↑",
       def:"Concentration is actively increasing compared to the prior daily snapshot. The pool is getting better, not just good."},
      {term:"Jackpot Gone",
       def:"All jackpot prizes have been claimed. The game may still have strong EV from mid-tier prizes but the top-end upside is gone."},
    ],
  },
  {
    title:"Velocity & Momentum (Detail View)",
    color:C.teal,
    entries:[
      {term:"Momentum",
       def:"The raw change in composite concentration between daily snapshots. Positive means concentration improved since yesterday. This answers: is the game getting better or worse right now?"},
      {term:"Win Rate Velocity",
       def:"How fast the win-rate ratio is changing per day. Positive means each remaining ticket is becoming more likely to be a winner at an accelerating rate."},
      {term:"Base Tier Velocity",
       def:"Average daily claim rate across common and uncommon prize tiers, normalized by total printed. This is how fast the everyday prizes are being claimed."},
      {term:"Top Tier Velocity",
       def:"Average daily claim rate across scarce, rare, and ultra-rare tiers. When this is lower than base tier velocity, rare prizes are being claimed more slowly and the pool is concentrating."},
      {term:"Velocity Divergence",
       def:"Base velocity minus top velocity. Positive = common prizes draining faster than rare ones = concentration is actively improving. This is the headline velocity signal shown on the card."},
    ],
  },
  {
    title:"Scoring System",
    color:C.gold,
    entries:[
      {term:"Composite Score",
       def:"The final ranking metric (adj_prof_score). Starts with a base score of ROI × maturity confidence × floor protection, then applies four sigmoid multipliers for concentration, jackpot concentration, win rate drift, and EV|win drift. Each multiplier is anchored to 1.0× at neutral, so no signal produces no adjustment."},
      {term:"Verdict Tiers",
       def:"Percentile-based labels recalibrated each run. Elite = top 5%, Strong Buy = top 18%, Consider = top 45%, Marginal = positive EV below top 45%, Avoid = EV at or below guarantee. These shift as the game universe changes. A game can move from Strong Buy to Consider without any change to its own metrics if the overall field improved."},
      {term:"Score Ring",
       def:"The circular gauge on each card. Normalized against the highest-scoring game in the current dataset (score_max), so #1 always reads 100 and relative positions are meaningful across the full range."},
    ],
  },
  {
    title:"Prize Table (Detail View)",
    color:C.purple,
    entries:[
      {term:"Tier Labels",
       def:"Prizes classified by scarcity: common (<1 in 500), uncommon (1 in 500+), scarce (1 in 5,000+), rare (1 in 50,000+), ultra-rare (1 in 500,000+). Only scarce and above are 'meaningful' for concentration analysis."},
      {term:"Deviation (pp)",
       def:"This tier's retention rate minus the game's overall retention rate, in percentage points. Positive means this tier is retaining better than average and prizes at this level are being claimed more slowly than the norm."},
      {term:"Retention",
       def:"Percentage of originally printed prizes still remaining (unclaimed). High retention on rare tiers = good; high retention on common tiers = not yet mature."},
      {term:"Vel/day",
       def:"Per-tier daily claim velocity: tickets claimed per day divided by total printed. Shows how fast each prize level is draining. Compare across tiers to see the concentration dynamic in action."},
      {term:"EV Anchor",
       def:"The smallest prize tier, marked in blue. Its claim rate is used to estimate sell-through because small prizes are cashed almost immediately after purchase."},
    ],
  },
];
function Guide(){
  const [open,setOpen]=useState({});
  return(
    <div style={{padding:"14px 16px 48px",maxWidth:700,margin:"0 auto"}}>
      <div style={{marginBottom:16}}>
        <div style={{fontSize:"1rem",fontWeight:700,color:C.text,marginBottom:4}}>Metric Guide</div>
        <div style={{fontSize:".68rem",color:C.dim,lineHeight:1.6}}>What every number, chart, and indicator means. Tap any section to expand.</div>
      </div>
      {GUIDE_SECTIONS.map((sec,si)=>(
        <div key={si} style={{marginBottom:14}}>
          <button onClick={()=>setOpen(o=>({...o,[si]:!o[si]}))}
            style={{width:"100%",textAlign:"left",background:C.s1,border:`1px solid ${C.b1}`,
              borderRadius:10,padding:"12px 14px",cursor:"pointer",display:"flex",
              justifyContent:"space-between",alignItems:"center"}}>
            <div style={{display:"flex",alignItems:"center",gap:8}}>
              <div style={{width:4,height:20,borderRadius:2,background:sec.color}}/>
              <span style={{fontSize:".82rem",fontWeight:600,color:C.text}}>{sec.title}</span>
              <span style={{fontSize:".6rem",color:C.dim}}>({sec.entries.length})</span>
            </div>
            <span style={{color:C.dim,fontSize:".8rem",transition:"transform .2s",
              transform:open[si]?"rotate(180deg)":"rotate(0)"}}>{"▾"}</span>
          </button>
          {open[si]&&(
            <div style={{background:C.s1,border:`1px solid ${C.b1}`,borderTop:"none",
              borderRadius:"0 0 10px 10px",padding:"6px 14px 10px"}}>
              {sec.entries.map((e,ei)=>(
                <div key={ei} style={{padding:"10px 0",borderBottom:ei<sec.entries.length-1?`1px solid ${C.b1}`:"none"}}>
                  <div style={{fontSize:".75rem",fontWeight:600,color:sec.color,marginBottom:4}}>{e.term}</div>
                  <div style={{fontSize:".68rem",color:C.sub,lineHeight:1.6}}>{e.def}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Roadmap ───────────────────────────────────────────────────────────────────
const ROADMAP = [
  {
    phase:"Next: Momentum Scoring (needs 7+ snapshots)",
    color:C.blue,
    items:[
      {title:"Momentum as Score Multiplier",metric:"sigmoid_mult(momentum, k=TBD, max_boost=±0.10)",
       desc:"Once 7+ daily snapshots smooth the velocity data, add momentum as a small multiplier to adj_prof_score. Games actively concentrating get a nudge; games diluting get dinged."},
    ],
  },
  {
    phase:"Phase 2: Systematic Detail Page Scraping",
    color:C.purple,
    items:[
      {title:"Time-Adjusted Pack Value",metric:"urgency_factor = 1 + (1 / days_until_close)",
       desc:"Games closing soon with strong metrics have an urgency premium. A closing game with 60% ROI scores higher than the same game with 300 days left."},
      {title:"Guaranteed Winners Efficiency",metric:"guarantee_winners = floor(guarantee / min_prize_amount)",
       desc:"How many winning tickets does the guarantee structure imply per pack by design?"},
    ],
  },
  {
    phase:"Phase 3: Historical Price Data",
    color:C.amber,
    items:[
      {title:"Cross-Price Normalized ROI",metric:"normalized_roi = roi_on_max_loss / sqrt(max_loss_per_pack)",
       desc:"Fairly compare $1 games to $100 games on one unified capital-efficiency axis."},
      {title:"Theoretical Minimum Pack Return",metric:"theoretical_min = expected_winners × min_prize_amount",
       desc:"Compare the state guarantee against the mathematical floor. Reveals whether the guarantee is meaningful or just marketing."},
    ],
  },
  {
    phase:"Phase 4: External Data",
    color:C.green,
    items:[
      {title:"Retailer Density Score",metric:"TX Lottery retailer locator API",
       desc:"High-volume retailers sell faster, meaning their packs reflect a more rapidly depleted pool than rural stores."},
      {title:"Second-Chance Drawing Value",metric:"Requires scraping active second-chance promotions",
       desc:"Some TX Lottery games add EV through second-chance drawings for non-winning tickets. Currently ignored entirely."},
    ],
  },
];
function Roadmap(){
  const [open,setOpen]=useState({});
  return(
    <div style={{padding:"14px 16px 48px"}}>
      <div style={{marginBottom:16}}>
        <div style={{fontSize:"1rem",fontWeight:700,color:C.text,marginBottom:4}}>Analysis Roadmap</div>
        <div style={{fontSize:".68rem",color:C.dim,lineHeight:1.6}}>Upcoming metrics and features, organized by data dependency. See the Guide tab for explanations of everything that's live.</div>
      </div>
      {ROADMAP.map((phase,pi)=>(
        <div key={pi} style={{marginBottom:14}}>
          <div style={{fontSize:".63rem",fontWeight:600,color:phase.color,textTransform:"uppercase",
            letterSpacing:".5px",marginBottom:8,padding:"6px 10px",background:phase.color+"15",borderRadius:6}}>
            {phase.phase}
          </div>
          {phase.items.map((item,ii)=>{
            const key=`${pi}-${ii}`;
            const isOpen=open[key];
            return(
              <div key={ii} style={{background:C.s1,border:`1px solid ${C.b1}`,borderRadius:10,marginBottom:8,overflow:"hidden"}}>
                <div onClick={()=>setOpen(o=>({...o,[key]:!o[key]}))}
                  style={{padding:"12px 14px",display:"flex",justifyContent:"space-between",alignItems:"center",cursor:"pointer"}}>
                  <div style={{fontSize:".82rem",fontWeight:600,color:C.text}}>{item.title}</div>
                  <span style={{color:C.dim,flexShrink:0,marginLeft:8}}>{isOpen?"▲":"▼"}</span>
                </div>
                {isOpen&&(
                  <div style={{padding:"0 14px 14px",borderTop:`1px solid ${C.b1}`}}>
                    <div style={{fontSize:".7rem",color:C.sub,lineHeight:1.7,marginTop:10,marginBottom:8}}>{item.desc}</div>
                    <div style={{background:C.s3,borderRadius:6,padding:"8px 10px"}}>
                      <div style={{fontSize:".55rem",color:C.dim,marginBottom:2}}>Formula / dependency</div>
                      <div style={{fontSize:".65rem",color:phase.color,fontFamily:"monospace",lineHeight:1.5}}>{item.metric}</div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────
class ErrorBoundary extends Component {
  constructor(props){super(props);this.state={error:null};}
  static getDerivedStateFromError(error){return {error};}
  render(){
    if(this.state.error) return(
      <div style={{padding:20,color:"#fff",background:"#1a1a2e",fontFamily:"monospace",whiteSpace:"pre-wrap"}}>
        <h2 style={{color:"red"}}>Render Error</h2>
        <p>{this.state.error.message}</p>
        <p>{this.state.error.stack}</p>
      </div>
    );
    return this.props.children;
  }
}

function AppInner(){
  const [DB,setDB]=useState(null);
  const [tab,setTab]=useState("games");
  const [selected,setSelected]=useState(null);
  const [verdictF,setVerdictF]=useState("actionable");
  const [priceF,setPriceF]=useState("all");
  const [sortKey,setSortKey]=useState("adj_score");
  const [search,setSearch]=useState("");

  useEffect(()=>{
    const base=import.meta.env.VITE_API_BASE_URL||"";
    fetch(`${base}/api/latest`)
      .then(r=>r.json())
      .then(data=>setDB(data))
      .catch(err=>console.error("Failed to load data:",err));
  },[]);

  const games=DB?.games||[];
  const asOf=DB?.asOf||"";
  const prices=useMemo(()=>[...new Set(games.map(g=>g.ticket_price))].sort((a,b)=>a-b),[games]);

  const filtered=useMemo(()=>{
    let list=[...games];
    if(search)         list=list.filter(g=>g.game_name.toLowerCase().includes(search.toLowerCase())||String(g.game_number).includes(search));
    if(priceF!=="all") list=list.filter(g=>g.ticket_price===parseFloat(priceF));
    if(verdictF==="actionable")  list=list.filter(g=>["elite","strong_buy","consider"].includes(g.verdict)&&!g.is_new_game);
    else if(verdictF==="elite")  list=list.filter(g=>g.verdict==="elite");
    else if(verdictF!=="all")    list=list.filter(g=>g.verdict===verdictF);
    list.sort((a,b)=>{
      if(sortKey==="adj_score")  return (b.adj_prof_score??-99)-(a.adj_prof_score??-99);
      if(sortKey==="roi")        return (b.roi_on_max_loss??-99)-(a.roi_on_max_loss??-99);
      if(sortKey==="ev")         return (b.ev_per_pack??-99)-(a.ev_per_pack??-99);
      if(sortKey==="win_rate")   return (b.win_rate_ratio??-99)-(a.win_rate_ratio??-99);
      if(sortKey==="evgw")       return (b.ev_given_win_ratio??-99)-(a.ev_given_win_ratio??-99);
      if(sortKey==="conc")       return (b.composite_conc??b.concentration_ratio??-99)-(a.composite_conc??a.concentration_ratio??-99);
      if(sortKey==="guar_adeq")  return (b.guarantee_adequacy??-99)-(a.guarantee_adequacy??-99);
      if(sortKey==="variance")   return (a.variance_score??99)-(b.variance_score??99);
      if(sortKey==="maxloss")    return (a.max_loss_per_pack??99999)-(b.max_loss_per_pack??99999);
      if(sortKey==="maturity")   return b.maturity-a.maturity;
      if(sortKey==="floor")      return (b.downside_protection??0)-(a.downside_protection??0);
      if(sortKey==="velocity")   return (b.velocity_divergence??-99)-(a.velocity_divergence??-99);
      if(sortKey==="momentum")   return (b.momentum??-99)-(a.momentum??-99);
      if(sortKey==="price")      return a.ticket_price-b.ticket_price;
      return a.game_name.localeCompare(b.game_name);
    });
    return list;
  },[games,search,priceF,verdictF,sortKey]);

  if(!DB) return (
    <div style={{display:"flex",alignItems:"center",justifyContent:"center",height:"100vh",fontFamily:"Poppins,sans-serif",background:"#1a1a2e",color:"#e0e0e0"}}>
      <div style={{textAlign:"center"}}>
        <div style={{fontSize:"2rem",marginBottom:"0.5rem"}}>Loading...</div>
        <div style={{color:"#888"}}>Fetching lottery data</div>
      </div>
    </div>
  );

  const elites  = games.filter(g=>g.verdict==="elite"&&g.adj_prof_score!=null);
  const buys    = games.filter(g=>g.verdict==="strong_buy"&&g.adj_prof_score!=null);
  const bestROI = [...elites,...buys].length ? Math.max(...[...elites,...buys].map(g=>g.roi_on_max_loss||0)) : 0;

  const ctrl={background:C.s2,border:`1px solid ${C.b1}`,color:C.text,
    fontFamily:"'Poppins',sans-serif",fontSize:".76rem",padding:"7px 11px",
    borderRadius:8,outline:"none",cursor:"pointer",width:"100%"};

  return(
    <div style={{minHeight:"100vh",background:C.bg,color:C.text,fontFamily:"'Poppins',sans-serif",margin:"0 auto"}}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap');
        *{box-sizing:border-box;margin:0;padding:0}
        ::-webkit-scrollbar{width:4px}
        ::-webkit-scrollbar-track{background:#18181c}
        ::-webkit-scrollbar-thumb{background:#333338;border-radius:2px}
        select option{background:#18181c}
        input::placeholder{color:#58586a}
        @keyframes tipIn{from{opacity:0;transform:translateX(-50%) translateY(4px)}to{opacity:1;transform:translateX(-50%) translateY(0)}}
        .card-grid{display:grid;grid-template-columns:1fr;gap:10px}
        @media(min-width:768px){.card-grid{grid-template-columns:1fr 1fr}}
        @media(min-width:1200px){.card-grid{grid-template-columns:1fr 1fr 1fr}}
        .detail-inner{max-width:700px;margin:0 auto}
      `}</style>

      {/* Header */}
      <div style={{background:C.s1,borderBottom:`1px solid ${C.b1}`,padding:"12px 16px 0",position:"sticky",top:0,zIndex:20}}>
        <div style={{maxWidth:1400,margin:"0 auto"}}>
        <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:10}}>
          <div>
            <div style={{fontSize:"1rem",fontWeight:700,color:C.text}}>
              TX Lottery <span style={{color:C.green}}>Pack Analyzer</span>
            </div>
            <div style={{fontSize:".58rem",color:C.dim,marginTop:1}}>Snapshot: {asOf}</div>
          </div>
          <div style={{display:"flex",gap:14}}>
            {[
              {label:"Elite",      val:elites.length, color:C.gold},
              {label:"Strong Buy", val:buys.length,   color:C.green},
              {label:"Best ROI",   val:pct(bestROI,0),color:C.green},
            ].map(({label,val,color})=>(
              <div key={label} style={{textAlign:"right"}}>
                <div style={{fontSize:".52rem",color:C.dim}}>{label}</div>
                <div style={{fontSize:".88rem",fontWeight:700,color}}>{val}</div>
              </div>
            ))}
          </div>
        </div>
        <div style={{display:"flex",gap:0,borderBottom:`1px solid ${C.b1}`}}>
          {[{id:"games",label:"Games"},{id:"guide",label:"Guide"},{id:"roadmap",label:"Roadmap"}].map(t=>(
            <button key={t.id} onClick={()=>setTab(t.id)}
              style={{flex:1,padding:"8px 0",background:"transparent",border:"none",
                borderBottom:`2px solid ${tab===t.id?C.green:"transparent"}`,
                color:tab===t.id?C.green:C.dim,fontFamily:"'Poppins',sans-serif",
                fontSize:".78rem",fontWeight:tab===t.id?600:400,cursor:"pointer"}}>
              {t.label}
            </button>
          ))}
        </div>
        </div>
      </div>

      {tab==="guide"?<Guide/>:tab==="roadmap"?<Roadmap/>:(
        <>
          <div style={{padding:"10px 16px 8px",background:C.s1,borderBottom:`1px solid ${C.b1}`}}>
            <div className="filter-bar" style={{display:"flex",flexWrap:"wrap",gap:8,maxWidth:1400,margin:"0 auto",alignItems:"center"}}>
              <input value={search} onChange={e=>setSearch(e.target.value)}
                placeholder="Search game name or number..."
                style={{...ctrl,padding:"9px 12px",flex:"1 1 200px",minWidth:150}}/>
              <select value={verdictF} onChange={e=>setVerdictF(e.target.value)} style={{...ctrl,flex:"0 1 160px"}}>
                <option value="actionable">Actionable</option>
                <option value="elite">Elite only</option>
                <option value="strong_buy">Strong Buy</option>
                <option value="consider">Consider</option>
                <option value="marginal">Marginal</option>
                <option value="all">All</option>
              </select>
              <select value={priceF} onChange={e=>setPriceF(e.target.value)} style={{...ctrl,flex:"0 1 130px"}}>
                <option value="all">All prices</option>
                {prices.map(p=><option key={p} value={p}>${p}</option>)}
              </select>
              <select value={sortKey} onChange={e=>setSortKey(e.target.value)} style={{...ctrl,flex:"0 1 220px"}}>
                <option value="adj_score">Sort: Composite Score</option>
                <option value="roi">Sort: ROI on Max Loss</option>
                <option value="ev">Sort: EV per Pack</option>
                <option value="win_rate">Sort: Win Rate Drift</option>
                <option value="evgw">Sort: EV|Win Drift</option>
                <option value="conc">Sort: Concentration Score</option>
                <option value="guar_adeq">Sort: Guarantee Adequacy</option>
                <option value="variance">Sort: Lowest Variance</option>
                <option value="maxloss">Sort: Lowest Max Loss</option>
                <option value="floor">Sort: Best Floor Protection</option>
                <option value="maturity">Sort: Most Mature</option>
                <option value="velocity">Sort: Velocity Divergence</option>
                <option value="momentum">Sort: Momentum</option>
                <option value="price">Sort: Ticket Price</option>
              </select>
            </div>
          </div>
          <div style={{padding:"6px 16px 4px",fontSize:".62rem",color:C.dim,maxWidth:1400,margin:"0 auto"}}>
            {filtered.length} game{filtered.length!==1?"s":""} · tap any card for full analysis
          </div>
          <div className="card-grid" style={{padding:"0 12px 24px",maxWidth:1432,margin:"0 auto"}}>
            {filtered.map((g,i)=><GameCard key={g.game_number} g={g} rank={i+1} onClick={setSelected} scoreMax={DB.score_max}/>)}
            {!filtered.length&&(
              <div style={{textAlign:"center",color:C.dim,padding:60,fontSize:".8rem",gridColumn:"1/-1"}}>No games match your filters.</div>
            )}
          </div>
        </>
      )}

      {selected&&<Detail g={selected} onClose={()=>setSelected(null)} scoreMax={DB.score_max}/>}
    </div>
  );
}

export default function App(){
  return <ErrorBoundary><AppInner/></ErrorBoundary>;
}
