'use client';
import {useEffect,useState} from 'react';
import {ExternalLink} from 'lucide-react';
import initial from '@/data/load-observations.json';
import collection from '@/data/load-collection.json';
import type {LoadObservation} from '@/lib/load-observation-schema';
import {LOAD_STAGE_LABELS} from '@/lib/load-observation-schema';
const value=(r:LoadObservation)=>(r.valueQualifier==='~'?'약 ':r.valueQualifier==='>'?'> ':r.valueQualifier==='>='?'≥ ':'')+r.valueGW!.toLocaleString('en-US',{maximumFractionDigits:4});
export default function LoadQueueSummary({region,refresh,loadRecords,context,onDetails,onResearch}:{region:string;refresh:number;loadRecords:number;context:{title:string;value:string;note:string;source:string};onDetails:()=>void;onResearch:()=>void}){
 const [rows,setRows]=useState(initial as LoadObservation[]),[notice,setNotice]=useState('');
 useEffect(()=>{const c=new AbortController();let stopped=false;const timeout=setTimeout(()=>c.abort(),20000);fetch('/api/load-data',{signal:c.signal}).then(r=>{if(!r.ok)throw new Error();return r.json()}).then((d:any)=>{if(!stopped){setRows(d.observations);setNotice(d.storageAvailable?'':'마지막 검증 공시 표시 · 저장소 확인 지연')}}).catch(()=>{if(!stopped)setNotice('마지막 검증 공시 표시 · 조회 재시도 필요')}).finally(()=>clearTimeout(timeout));return()=>{stopped=true;clearTimeout(timeout);c.abort()}},[refresh]);
 const local=rows.filter(r=>r.region===region&&r.valueGW!==null);
 const preferred=region==='ERCOT'?['ERCOT_LARGE_LOAD_REQUESTS_20260618','ERCOT_ONCOR_DC_REQUESTS_2026Q2','ERCOT_CENTERPOINT_BATCHZERO_SUBMISSION_20260728']:[];
 const selected=preferred.length?preferred.map(id=>local.find(r=>r.id===id)).filter((r):r is LoadObservation=>!!r):local.filter(r=>r.stageClass!=='energized').sort((a,b)=>b.publicationDate.localeCompare(a.publicationDate)).slice(0,3);
 const guide=collection.find(r=>r.region===region)!;
 return <section className="panel load-queue-summary"><div className="panel-header"><div><p className="eyebrow">LARGE LOAD REQUESTS</p><h3>{local.length?'공개 부하 집계 확보':'공식 부하 자료'} · {loadRecords?'개별 참고 원장 별도':'개별 프로젝트 원장 미확보'}</h3></div><button className="source-button" onClick={onDetails}>전체 부하 공시·근거 보기</button></div><p className="load-queue-explanation">{loadRecords?'아래 표는 수록한 개별 프로젝트 목록. 공개 집계와 원장의 대상 범위·단계 차이 확인 필요.':'개별 프로젝트 명세 미확보는 신청 물량 부재와 다른 의미. 확인된 공식 요청·계약 용량은 아래 집계로 표시.'}</p>
 <div className="load-request-cards">{selected.map(r=><article key={r.id}><span>{r.operator} · {LOAD_STAGE_LABELS[r.stageClass]}</span><h4>{r.metricLabel}</h4><strong>{value(r)} <small>GW</small></strong><p>{r.scope}</p><p className="micro">{r.asOf?'기준 '+r.asOf.replaceAll('-','.'):'정확 기준일 미명시'} · 발표 {r.publicationDate.replaceAll('-','.')}</p><a href={r.sourceUrl} target="_blank" rel="noreferrer">공식 원문 <ExternalLink size={12}/></a></article>)}{!selected.length&&<article><span>{context.title}</span><strong>{context.value}</strong><p>{context.note}</p><a href={context.source} target="_blank" rel="noreferrer">공식 원문 <ExternalLink size={12}/></a></article>}</div>
 {region==='ERCOT'&&<div className="ercot-report-context"><b>{context.title}: {context.value}</b><p>{context.note}</p><a href={context.source} target="_blank" rel="noreferrer">Batch Zero 원문 <ExternalLink size={12}/></a></div>}
 <button className="text-action research-bridge" onClick={onResearch}>공개 제한·접속 절차의 정성 근거 읽기 →</button><div className="load-queue-boundary"><div><b>프로젝트별 병목 점수</b><p>고객 ID·용량·접속 단계 연결이 필요한 지표. 개별 원장 미확보 구간은 점수 미산출.</p></div><div><b>{region==='ERCOT'?'개별 명세 공개 제한':'남은 수집 공백'}</b><p>{region==='ERCOT'?'ERCOT NPRR1267에서 고객 정보의 기밀성을 이유로 대규모 부하의 집계 공개 명시. 고객별 명칭·MW·단계가 연결된 공개 전수 원장 미확보.':guide.remainingGap}</p>{region==='ERCOT'&&<a href="https://www.ercot.com/mktrules/issues/NPRR1267" target="_blank" rel="noreferrer">NPRR1267 공식 근거 <ExternalLink size={12}/></a>}</div></div><p className="chart-note">서로 다른 기준일·대상 집합의 관측값 · 기관 간 중복 및 가동분 포함 가능성에 따라 합산 제외{notice?' · '+notice:''}</p></section>
}
