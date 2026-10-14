'use client';
import {useEffect,useState} from 'react';
import {ExternalLink,RefreshCw,ArrowRight,AlertTriangle} from 'lucide-react';
import {GATE_LABELS,STATE_LABELS,KIND_LABELS,CAPACITY_LABELS,type NewsEvent} from '@/lib/newsflow-schema';
import './newsflow.css';
const date=(v?:string|null)=>v?v.slice(0,10):'원문 일자 미확인';
type Result={events:NewsEvent[];total:number;last_sync?:{at:string;status:string};gate_summary?:{gate:string;status:string;published_at:string|null;event_id:string|null;remaining_requirements:string[]}[]};
function EventCard({e,onAsset}:{e:NewsEvent;onAsset?:(id:string)=>void}){
 return <article className="nf-event"><div className="nf-event-top"><span className="nf-eyebrow">{e.region} · {KIND_LABELS[e.asset_kind]} · {e.state||'주 미확인'}</span><time>{date(e.published_at)}</time></div>
 <h3>{onAsset?<button onClick={()=>onAsset(e.asset_id)}>{e.asset_name}</button>:e.asset_name}</h3>
 <div className="nf-badges"><span>{GATE_LABELS[e.gate]}</span><span className={'nf-status nf-'+e.status}>{STATE_LABELS[e.status]}</span><span>{e.certainty==='confirmed'?'확인된 사실':e.certainty==='conditional'?'조건부 사실':'제안·계획'}</span><span>{e.direction==='improved'?'병목 완화 방향':e.direction==='worsened'?'병목 강화 방향':e.direction==='neutral'?'단계 진행·방향 중립':'병목 방향 미확인'}</span>{e.provenance==='legacy_verified_context'&&<span>과거 검토자료 · 단계 매핑 미완료</span>}</div>
 <div className="nf-change"><p>{e.previous_fact||'기존 상태 미확인'}</p><ArrowRight size={16}/><p>{e.new_fact}</p></div>
 {e.capacity&&<p className="nf-capacity">{e.capacity.mw.toLocaleString()} MW · {CAPACITY_LABELS[e.capacity.basis]}{e.capacity.qualifier?' · '+e.capacity.qualifier:''}</p>}
 <div className="nf-remaining"><strong>남은 요건·확인 공백</strong>{e.remaining_requirements.length?<ul>{e.remaining_requirements.map((x,i)=><li key={i}>{x}</li>)}</ul>:<p>추가 요건 개별 확인 미확보 · 전체 병목 해소를 의미하지 않음</p>}</div>
 <footer><div><span>대시보드 반영</span><span>{e.telegram.status==='delivered_ack'?'텔레그램 발송·ACK 확인':'텔레그램 미발송'}</span><span>{e.matched_project_id?'공식 ID 원장 연결':e.asset_kind==='policy'?'지역 정책 · 프로젝트 승인 아님':'원장 연결 미확정'}</span></div><div>{e.source_urls.map((u,i)=><a key={u} href={u} target="_blank" rel="noreferrer">{e.source_urls.length>1?'근거 '+(i+1):'원문보기'} <ExternalLink size={12}/></a>)}</div></footer>
 </article>
}
export default function NewsflowPanel({region,refresh,project}:{region:string;refresh:number;project?:string}){
 const [scope,setScope]=useState('all'),[gate,setGate]=useState('all'),[asset,setAsset]=useState(''),[page,setPage]=useState(0),[data,setData]=useState<Result|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(false),[local,setLocal]=useState(0),[context,setContext]=useState(false);
 useEffect(()=>{setPage(0);setAsset('')},[region]);
 useEffect(()=>{const c=new AbortController();const timeout=setTimeout(()=>c.abort(),20000);setLoading(true);setError('');const p=new URLSearchParams({region:project?'all':scope==='region'?region:'all',gate,context:context?'1':'0',limit:'20',offset:String(page*20)});if(project)p.set('project',project);if(asset)p.set('asset',asset);
 let stop=false;fetch('/api/newsflow?'+p,{signal:c.signal}).then(async r=>{if(!r.ok)throw new Error();return r.json() as Promise<Result>}).then(d=>{if(!stop){setData(d);setLoading(false)}}).catch(()=>{if(!stop){setError('뉴스 변경 이력 조회 실패 · 0건으로 판정하지 않음');setLoading(false)}}).finally(()=>clearTimeout(timeout));return()=>{stop=true;clearTimeout(timeout);c.abort()}},[region,scope,gate,asset,page,refresh,local,project,context]);
 useEffect(()=>{const t=setInterval(()=>setLocal(v=>v+1),60000);return()=>clearInterval(t)},[]);
 return <section className="nf-panel"><div className="section-heading"><div><p className="eyebrow">NEWSFLOW × GRID OBSERVATORY</p><h2>{project?'프로젝트 산업 변화 이력':'산업 변화 · 병목 관문'}</h2></div><button className="icon-button" onClick={()=>setLocal(v=>v+1)} aria-label="변경 이력 새로고침"><RefreshCw size={17}/></button></div>
 <p className="nf-note">뉴스의 확인된 변경만 기록. 공식 큐의 원본 단계·총량과 분리. 인허가 승인 ≠ 접속 완료. 전력계약 MW ≠ 접속신청 MW.</p>
 {!project&&<label className="nf-note"><input type="checkbox" checked={context} onChange={e=>{setContext(e.target.checked);setPage(0)}}/> 과거 검토자료·관문 매핑 미완료 기록 포함</label>}
 {!project&&<div className="nf-toolbar"><label>권역<select value={scope} onChange={e=>{setScope(e.target.value);setPage(0)}}><option value="all">전체 · 미확인 포함</option><option value="region">선택 권역 {region}</option></select></label><label>관문<select value={gate} onChange={e=>{setGate(e.target.value);setPage(0)}}><option value="all">전체 관문</option>{Object.entries(GATE_LABELS).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>{asset&&<button onClick={()=>{setAsset('');setPage(0)}}>프로젝트 필터 해제</button>}</div>}
 <div className="nf-summary"><span>{data?`${data.total}개 확인 이력`:'조회 중'}</span><span>최근 수신 {data?.last_sync?.at?new Date(data.last_sync.at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})+' KST':'미확인'}</span></div>
 {!!data?.gate_summary?.length&&<div className="nf-gates">{data.gate_summary.map(g=><div key={g.gate}><strong>{GATE_LABELS[g.gate]}</strong><span>{g.status==='conflicting'?'동일일 근거 상충 · 재확인 필요':STATE_LABELS[g.status]}</span><small>{date(g.published_at)}</small></div>)}</div>}
 {error?<p className="notice"><AlertTriangle size={16}/>{error}</p>:loading?<p className="nf-empty">변경 이력 조회 중</p>:!data?.events.length?<p className="nf-empty">조건에 맞는 연결 이력 미확보 · 실제 산업 변화 없음이나 모든 프로젝트 검토 완료를 의미하지 않음</p>:data.events.map(e=><EventCard key={e.id} e={e} onAsset={project?undefined:id=>{setAsset(id);setPage(0)}}/>)}
 {data&&data.total>20&&<div className="nf-pagination"><button disabled={!page} onClick={()=>setPage(p=>p-1)}>이전</button><span>{page+1} / {Math.ceil(data.total/20)}</span><button disabled={(page+1)*20>=data.total} onClick={()=>setPage(p=>p+1)}>다음</button></div>}
 </section>
}
