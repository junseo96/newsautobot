import {env} from 'cloudflare:workers';
import initial from '@/data/projects-snapshot';
import seed from '@/data/seed.json';
import type {Project} from './grid-types';
export function binding(){if(!env.DB)throw new Error('저장소 연결 미확인');return env.DB;}
const normalizedRegion=(r:string)=>r==='Non-RTO West'?'West':r;
const normalizedProject=(p:Project)=>p.kind==='load'?{...p,region:normalizedRegion(p.region)}:p;
export const initialProjects=initial as unknown as Project[];
export async function projectsFor(region?:string,strict=false){
 let projects=initialProjects.filter(p=>!region||p.region===region);
 try{
  const query="SELECT key,kind,region,source_as_of,updated_at,payload FROM datasets WHERE kind IN ('generation','load','load-register')";
  const q=region?binding().prepare(query+' AND region IN (?,?)').bind(region,region==='West'?'Non-RTO West':region):binding().prepare(query);
  const rows=await q.all<{key:string;kind:string;region:string;source_as_of:string;updated_at:string;payload:string}>();
  const datasets=rows.results.filter(r=>['generation','load'].includes(r.kind)).map(r=>{const data=JSON.parse(r.payload);return{...r,region:r.kind==='load'?normalizedRegion(r.region):r.region,data:{...data,records:data.records.map(normalizedProject)}}});
  const registers=new Map<string,Array<{row:typeof rows.results[number];data:any}>>();
  for(const row of rows.results.filter(r=>r.kind==='load-register')){const data=JSON.parse(row.payload),key=row.region+'|'+data.operator;registers.set(key,[...(registers.get(key)||[]),{row,data}])}
  for(const parts of registers.values()){const newest=parts.map(p=>p.data.revision as string).sort().at(-1),current=parts.filter(p=>p.data.revision===newest).sort((a,b)=>a.data.part-b.data.part),first=current[0];if(!first||current.length!==first.data.parts||current.some((p,i)=>p.data.part!==i))throw new Error('수용가 원장 분할 저장 완결성 오류');datasets.push({...first.row,kind:'load',region:normalizedRegion(first.row.region),data:{operator:first.data.operator,records:current.flatMap(p=>p.data.records.map(normalizedProject))}})}
  datasets.sort((a,b)=>a.source_as_of.localeCompare(b.source_as_of)||a.updated_at.localeCompare(b.updated_at)||Number(Boolean(a.data.operator))-Number(Boolean(b.data.operator))||a.key.localeCompare(b.key));
  for(const r of datasets){
   const inScope=(p:Project)=>p.region===r.region&&p.kind===r.kind&&(!r.data.operator||p.operator===r.data.operator);
   if(projects.some(p=>inScope(p)&&p.asof>r.source_as_of))continue;
   projects=projects.filter(p=>!inScope(p));projects.push(...r.data.records as Project[]);
  }
 }catch(e){if(strict)throw e;console.error('queue read fallback',e instanceof Error?e.message:e)}
 return projects;
}
export function summarize(projects:Project[],region:string){
 const g=projects.filter(p=>p.region===region&&p.kind==='generation'&&p.include===1&&!['W','G8'].includes(p.stage));
 const l=projects.filter(p=>p.region===region&&p.kind==='load');
 const valid=l.filter(p=>p.include===1&&typeof p.mw==='number'&&!['W','G8'].includes(p.stage));
 const weight=g.reduce((s,p)=>s+Math.max(0,Number(p.mw)||0),0);
 const dates=[...new Set(g.map(p=>p.asof))].sort();
 return{id:region,generationGW:g.reduce((s,p)=>s+Number(p.mw||0),0)/1000,storageGW:g.reduce((s,p)=>s+(p.storageMw||0),0)/1000,generationCount:g.length,loadGW:valid.length?valid.reduce((s,p)=>s+Number(p.mw),0)/1000:null,loadCount:valid.length||null,loadRecords:l.length,scoreLow:weight?g.reduce((s,p)=>s+Math.max(0,Number(p.mw)||0)*Number(p.low),0)/weight:null,scoreHigh:weight?g.reduce((s,p)=>s+Math.max(0,Number(p.mw)||0)*Number(p.high),0)/weight:null,unknownCount:g.filter(p=>['GU','GC','GN','GS'].includes(p.stage)).length,generationAsOf:dates.length===1?dates[0]:dates.length?'권역 내 기준일 혼재':null,generationAsOfMin:dates[0]||null,generationAsOfMax:dates.at(-1)||null,stages:seed.stages.map(st=>({code:st.code,label:st.label,gw:g.filter(p=>p.stage===st.code).reduce((s,p)=>s+Number(p.mw||0),0)/1000,storageGW:g.filter(p=>p.stage===st.code).reduce((s,p)=>s+(p.storageMw||0),0)/1000,count:g.filter(p=>p.stage===st.code).length,loadGW:valid.length?valid.filter(p=>p.stage===st.code).reduce((s,p)=>s+Number(p.mw||0),0)/1000:null}))};
}
export async function summary(){const p=await projectsFor();return seed.regions.map(r=>summarize(p,r.id));}

export function compactLoadProject(p:Project){if(p.kind!=="load")return p;const r={...p} as Record<string,unknown>;for(const k of ["sourceFields","assessmentHistory","studyEvidence","sourceDateEvidence","studyMentions","sourceProvenance","rawFields","rawCells","rawSourceFields"])delete r[k];return r as Project}
