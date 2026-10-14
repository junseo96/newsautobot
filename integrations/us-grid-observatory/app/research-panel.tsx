'use client';
import {useEffect,useMemo,useState} from 'react';
import {BookOpen,ChevronRight,ExternalLink,Search} from 'lucide-react';
import {Input} from '@/components/ui/input';
import {researchItems,RESEARCH_CATEGORIES,type ResearchItem} from '@/lib/research-items';
import type {QualitativeNote} from '@/lib/qualitative-schema';
import type {LoadObservation} from '@/lib/load-observation-schema';
import {REGION_LABELS} from '@/lib/grid-types';
import notes from '@/data/qualitative-notes.json';
import observations from '@/data/load-observations.json';
import seed from '@/data/seed.json';
const initial=researchItems(notes as QualitativeNote[],observations as LoadObservation[],seed.policies);
const label=(r:string)=>r==='US'?'전국·공통':REGION_LABELS[r]||r;
export default function ResearchPanel({region,refresh}:{region:string;refresh:number}){
 const [items,setItems]=useState<ResearchItem[]>(initial),[error,setError]=useState(''),[all,setAll]=useState(false),[category,setCategory]=useState('전체'),[query,setQuery]=useState(''),[selected,setSelected]=useState(''),[page,setPage]=useState(0),[history,setHistory]=useState<{checkedAt:string;count:number;changed:number}[]>([]);
 useEffect(()=>{const c=new AbortController(),timer=setTimeout(()=>c.abort(),20000);let stopped=false;
 fetch('/api/research',{signal:c.signal}).then(r=>{if(!r.ok)throw new Error();return r.json()}).then((d:any)=>{if(stopped)return;setItems(d.items);setHistory(d.history);setError(d.storageAvailable?'':'저장소 확인 지연 · 마지막 검증 자료 표시')}).catch(()=>{if(!stopped)setError('조회 지연 · 마지막 검증 자료 유지 · 상단 새로고침으로 재시도 가능')}).finally(()=>clearTimeout(timer));return()=>{stopped=true;clearTimeout(timer);c.abort()}},[refresh]);
 useEffect(()=>{setSelected('');setPage(0);setQuery('');setAll(false)},[region]);
 const scoped=useMemo(()=>items.filter(r=>all||r.regions.includes(region)||r.regions.includes('US')),[items,all,region]);
 const filtered=useMemo(()=>scoped.filter(r=>(category==='전체'||r.category===category)&&[r.title,r.summary,...r.facts,r.interpretation,r.limitations,r.nextCheck,r.sourceTitle,r.status,...r.regions].join(' ').toLowerCase().includes(query.toLowerCase())),[scoped,category,query]);
 const visible=filtered.slice(page*12,page*12+12),detail=visible.find(r=>r.id===selected)||visible[0];
 const reset=()=>{setPage(0);setSelected('')};
 return <div className="research-view"><div className="section-heading"><div><p className="eyebrow">EVIDENCE LIBRARY</p><h2>숫자 뒤의 근거자료실</h2><p className="load-subtitle">공개 범위·접속 절차·계약 정의·정책 상태를 원문과 함께 확인</p></div><span className="tag">9개 권역 + 전국·공통</span></div>
 <div className="research-summary"><BookOpen size={23}/><p><strong>{items.filter(r=>r.category==='정성 해설').length}개 정성 해설과 공시 근거의 통합 열람</strong><span>왼쪽 자료 선택 → 핵심 사실·해석·한계 확인 → 공식 원문 열기</span></p><span>{items.length}개 수록 항목</span></div>
 <div className="research-controls"><div className="research-scope"><button className={!all?'active':''} aria-pressed={!all} onClick={()=>{setAll(false);reset()}}>{label(region)} + 공통</button><button className={all?'active':''} aria-pressed={all} onClick={()=>{setAll(true);reset()}}>전국 전체</button></div><div className="search-wrap"><Search size={16}/><Input aria-label="근거자료 검색" placeholder="기밀·계약·Batch Zero·기관 검색" value={query} onChange={e=>{setQuery(e.target.value);reset()}}/></div></div>
 <div className="research-categories" aria-label="근거 종류">{['전체',...RESEARCH_CATEGORIES].map(c=><button key={c} aria-pressed={category===c} className={category===c?'active':''} onClick={()=>{setCategory(c);reset()}}>{c}<span>{scoped.filter(r=>c==='전체'||r.category===c).length}</span></button>)}</div>
 {error&&<p className="research-notice" role="status">{error}</p>}
 <div className="research-layout"><aside className="panel research-list" aria-label="근거자료 목록"><div className="research-list-header"><span>검색 결과 {filtered.length}건</span><span>{all?'전국 전체':label(region)+' + 공통'}</span></div>{visible.map(r=><button key={r.id} className={'research-item '+(r.id===detail?.id?'selected':'')} aria-pressed={r.id===detail?.id} onClick={()=>setSelected(r.id)}><span className="research-item-meta">{r.regions.map(label).join(' · ')}<small>{r.category}</small></span><strong>{r.title}</strong><p>{r.summary}</p><span className="research-item-footer">{r.checkedAt?'확인 '+r.checkedAt:r.status}<ChevronRight size={15}/></span></button>)}{!visible.length&&<p className="research-empty">검색 조건에 맞는 자료 없음</p>}<div className="research-pages"><button disabled={page===0} onClick={()=>{setPage(p=>p-1);setSelected('')}}>이전</button><span>{page+1} / {Math.max(1,Math.ceil(filtered.length/12))}</span><button disabled={(page+1)*12>=filtered.length} onClick={()=>{setPage(p=>p+1);setSelected('')}}>다음</button></div></aside>
 {detail?<article className="panel research-detail" aria-label="선택 근거 상세"><div className="research-detail-top"><span className="eyebrow">{detail.regions.map(label).join(' · ')} / {detail.category}</span><span className={'tag '+(detail.status.includes('불일치')?'research-discrepancy':'')}>{detail.status}</span></div><h3>{detail.title}</h3><p className="research-lede">{detail.summary}</p><p className="research-dates">{detail.dateLabel}<br/>확인일 {detail.checkedAt||'개별 확인일 미기록'}</p><section className="research-facts"><h4>핵심 확인 내용</h4><ul>{detail.facts.map((f,i)=><li key={i}>{f}</li>)}</ul></section><section><h4>관측소 해석</h4><p>{detail.interpretation}</p></section><section className="research-limits"><h4>공개 한계·주의할 해석</h4><p>{detail.limitations}</p></section><section><h4>다음 확인사항</h4><p>{detail.nextCheck}</p></section><div className="research-original"><h4>공식 원문</h4><p>{detail.sourceTitle}</p>{detail.sourceUrls.map((url,i)=><a key={url} className="source-button" href={url} target="_blank" rel="noreferrer">원문 {detail.sourceUrls.length>1?i+1:''} 열기<ExternalLink size={14}/></a>)}<small>원문에 근거한 요약 · 자료별 모집단·기준일 유지</small></div></article>:<div className="panel research-detail research-empty">필터 변경 후 자료 선택</div>}</div>
 <details className="research-history"><summary>정성 해설 확인 이력 · {history.length}회</summary>{history.length?history.map((h,i)=><p key={i}>{h.checkedAt.replace('T',' ').slice(0,16)} UTC · {h.count}건 확인 · 내용 변경 {h.changed}건</p>):<p>최초 게시 자료 · 다음 확인부터 저장 이력 누적</p>}</details>
 </div>
}
