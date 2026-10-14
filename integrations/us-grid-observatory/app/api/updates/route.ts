import {z} from 'zod';
import {loadObservationSchema} from '@/lib/load-observation-schema';
import {loadObservations} from '@/lib/load-observations';
import {qualitativeSchema} from '@/lib/qualitative-schema';
import {qualitativeNotes} from '@/lib/qualitative-notes';
import {namedLoadSchema} from '@/lib/named-load-schema';
import {namedLoads} from '@/lib/named-loads';
import {censusSourceSchema} from '@/lib/load-census-schema';
import {censusSources} from '@/lib/load-census';
import {binding,initialProjects,projectsFor,summarize} from '@/lib/grid-db';
import {liveData} from '@/lib/live-data';
import seed from '@/data/seed.json';
import type {Project} from '@/lib/grid-types';
const regions=seed.regions.map(r=>r.id);
const validDate=z.string().regex(/^\d{4}-\d{2}-\d{2}$/).refine(v=>!Number.isNaN(Date.parse(v))&&new Date(v).toISOString().slice(0,10)===v,'유효 기준일 필요');
const record=z.object({id:z.string().min(1).max(200),region:z.string(),operator:z.string().min(1),queueId:z.string(),name:z.union([z.string(),z.number()]),kind:z.enum(['generation','load']),mw:z.union([z.number().finite(),z.string(),z.null()]),stage:z.enum(['G1','G2','G3','GC','G4','G5','G6','G7','G8','GU','GN','GS','BC','W']),include:z.union([z.literal(0),z.literal(1)]),source:z.string().url(),storageMw:z.number().finite().nullable().optional(),asof:validDate,low:z.union([z.number(),z.string()]),high:z.union([z.number(),z.string()])}).passthrough();
async function snapshot(region:string,now:string){const s=summarize(await projectsFor(region),region);await binding().prepare('INSERT INTO snapshots(id,region,observed_at,payload) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET observed_at=excluded.observed_at,payload=excluded.payload').bind(region+':'+now.slice(0,10),region,now,JSON.stringify(s)).run();}
async function saveLive(id:string,now:string){const l=await liveData(id);if(l.status==='available')await binding().prepare('INSERT INTO datasets(key,kind,region,source_as_of,source_url,payload,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET source_as_of=excluded.source_as_of,payload=excluded.payload,updated_at=excluded.updated_at').bind('live:'+id,'live',id,l.observedAt,l.sourceUrl,JSON.stringify(l),now).run();return {id,status:l.status,observedAt:l.observedAt};}
export async function POST(request:Request){
 const origin=request.headers.get('origin');if(origin&&origin!==new URL(request.url).origin)return Response.json({error:'교차 출처 쓰기 차단'},{status:403});
 try{const text=await request.text();if(text.length>14000000)return Response.json({error:'요청 크기 초과'},{status:413});const body=JSON.parse(text);const now=new Date().toISOString();let details:unknown;
 if(body.action==='initialize'){
  for(const region of regions)await snapshot(region,now);
  details={queueBaseline:'2025-12-31',regions:regions.length};
 }else if(body.action==='refresh-live'){
  const ids=z.array(z.enum(['US48','CISO','ERCO','ISNE','MISO','NYIS','PJM','SWPP','SWPW','BPAT','SOCO','DUK','TVA','FPL','PACE','PACW','AZPS','NEVP'])).max(18).parse(body.ids||['US48','CISO','ERCO','ISNE','MISO','NYIS','PJM','SWPP','SWPW','BPAT','SOCO']);const results=[];
  for(let i=0;i<ids.length;i+=3)results.push(...await Promise.all(ids.slice(i,i+3).map(async id=>{try{return await saveLive(id,now)}catch(e){return{id,status:'failed',error:e instanceof Error?e.message:'조회 오류'}}})));
  details=results;
  }else if(body.action==='ingest-live'){
 const l=z.object({id:z.string(),name:z.string(),source:z.literal('EIA-930'),sourceUrl:z.string().url(),observedAt:z.string().datetime(),mixObservedAt:z.string().datetime().optional(),retrievedAt:z.string().datetime(),timezone:z.literal('UTC'),interval:z.string(),loadGW:z.number().finite().nonnegative(),generationGW:z.number().finite().nullable(),mix:z.array(z.object({fuel:z.string(),gw:z.number().finite()})).max(30),series:z.array(z.object({time:z.string().datetime(),loadGW:z.number().finite().nullable()}).passthrough()).max(200),warning:z.string().optional()}).parse(body.data);
 if(!['US48','CISO','ERCO','ISNE','MISO','NYIS','PJM','SWPP','SWPW','BPAT','SOCO','DUK','TVA','FPL','PACE','PACW','AZPS','NEVP'].includes(l.id)||new URL(l.sourceUrl).hostname!=='www.eia.gov')throw new Error('운영자료 출처/기관 검증 실패');
 const previous=await binding().prepare('SELECT source_as_of FROM datasets WHERE key=?').bind('live:'+l.id).first<{source_as_of:string}>();if(previous&&previous.source_as_of>l.observedAt)throw new Error('과거 운영자료 덮어쓰기 차단');
 await binding().prepare('INSERT INTO datasets(key,kind,region,source_as_of,source_url,payload,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET source_as_of=excluded.source_as_of,payload=excluded.payload,updated_at=excluded.updated_at').bind('live:'+l.id,'live',l.id,l.observedAt,l.sourceUrl,JSON.stringify({...l,status:'available'}),now).run();details={id:l.id,observedAt:l.observedAt};
 }else if(body.action==='ingest'){
  const kind=z.enum(['generation','load']).parse(body.kind),region=z.string().refine(r=>regions.includes(r)).parse(body.region),sourceAsOf=validDate.parse(body.sourceAsOf),sourceUrl=z.string().url().parse(body.sourceUrl);const records=z.array(record).min(1).max(12000).parse(body.records);
  if(records.some(r=>r.region!==region||r.kind!==kind||r.asof!==sourceAsOf)||new Set(records.map(r=>r.id)).size!==records.length)throw new Error('권역·종류 또는 키 중복 오류');
  const stageMap=new Map(seed.stages.map(s=>[s.code,s]));for(const r of records){const st=stageMap.get(r.stage)!;r.low=st.low;r.high=st.high;if(['W','G8'].includes(r.stage))r.include=0;if(r.kind==='load'&&r.include===1&&(r.region!=='NYISO'||typeof r.mw!=='number'||['W','G8'].includes(r.stage)))throw new Error('유효 부하 범위 검증 실패');if(r.kind==='generation'&&typeof r.mw!=='number')throw new Error('발전 공개 MW 숫자 필요');}
  const operator=typeof body.operator==='string'?body.operator:null;if(operator&&records.some(r=>r.operator!==operator))throw new Error('사업자 범위 오류');
  const key=kind+':'+region+(operator?':'+operator:'');const prior=await binding().prepare('SELECT source_as_of FROM datasets WHERE key=?').bind(key).first<{source_as_of:string}>();if(prior&&prior.source_as_of>sourceAsOf)throw new Error('이전 기준일로 덮어쓰기 차단');
  const overlapping=await binding().prepare('SELECT source_as_of,payload FROM datasets WHERE kind=? AND region=?').bind(kind,region).all<{source_as_of:string;payload:string}>();if(overlapping.results.some(d=>{const scope=JSON.parse(d.payload).operator;return(!operator||!scope||scope===operator)&&d.source_as_of>sourceAsOf}))throw new Error('겹치는 범위의 최신 자료보다 과거 입력 차단');
  const before=(await projectsFor(region,true)).filter(p=>p.kind===kind&&(!operator||p.operator===operator));if(before.some(p=>p.asof>sourceAsOf))throw new Error('현행 원장보다 과거 기준일 입력 차단');const oldMap=new Map(before.map(p=>[p.id,p]));const newIds=new Set(records.map(p=>p.id));
  const changes={added:records.filter(p=>!oldMap.has(p.id)).length,removed:before.filter(p=>!newIds.has(p.id)).length,stageChanged:records.filter(p=>oldMap.has(p.id)&&oldMap.get(p.id)!.stage!==p.stage).length};
  await binding().prepare('INSERT INTO datasets(key,kind,region,source_as_of,source_url,payload,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET source_as_of=excluded.source_as_of,source_url=excluded.source_url,payload=excluded.payload,updated_at=excluded.updated_at').bind(key,kind,region,sourceAsOf,sourceUrl,JSON.stringify({records,operator,changes,note:body.note||''}),now).run();await snapshot(region,now);details={kind,region,sourceAsOf,count:records.length,changes};
 }else if(body.action==='ingest-load-register'){
  const region=z.string().refine(r=>regions.includes(r)).parse(body.region),operator=z.string().min(1).max(200).parse(body.operator),sourceAsOf=validDate.parse(body.sourceAsOf),sourceUrl=z.string().url().parse(body.sourceUrl),records=z.array(record).min(1).max(15000).parse(body.records);
  if(sourceAsOf>now.slice(0,10)||records.some(r=>r.kind!=='load'||r.region!==region||r.operator!==operator||r.asof>sourceAsOf)||new Set(records.map(r=>r.id)).size!==records.length)throw new Error('원장 범위·기준일·중복 검증 실패');
  const stages=new Map(seed.stages.map(s=>[s.code,s]));for(const r of records){const st=stages.get(r.stage)!;r.low=st.low;r.high=st.high;if(['W','G8'].includes(r.stage))r.include=0;if(r.include===1&&(region!=='NYISO'||typeof r.mw!=='number'))throw new Error('유효 부하 원장 범위 검증 실패');}
  const before=(await projectsFor(region,true)).filter(p=>p.kind==='load'&&p.operator===operator);if(before.some(p=>p.asof>sourceAsOf))throw new Error('현행 원장보다 과거 기준일 입력 차단');const oldMap=new Map(before.map(r=>[r.id,r])),newIds=new Set(records.map(r=>r.id)),changes={added:records.filter(r=>!oldMap.has(r.id)).length,removed:before.filter(r=>!newIds.has(r.id)).length,stageChanged:records.filter(r=>oldMap.has(r.id)&&oldMap.get(r.id)!.stage!==r.stage).length};
  const groups=[];let group:typeof records=[];let size=0;for(const r of records){const bytes=new TextEncoder().encode(JSON.stringify(r)).length;if(bytes>800000)throw new Error('개별 원장 행 크기 초과');if(size+bytes>800000&&group.length){groups.push(group);group=[];size=0}group.push(r);size+=bytes}if(group.length)groups.push(group);if(groups.length>80)throw new Error('원장 분할 수 초과');
  const id=crypto.randomUUID(),statements=groups.map((part,i)=>binding().prepare('INSERT INTO datasets(key,kind,region,source_as_of,source_url,payload,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET source_as_of=excluded.source_as_of,source_url=excluded.source_url,payload=excluded.payload,updated_at=excluded.updated_at').bind('load-register:'+region+':'+operator+':'+i,'load-register',region,sourceAsOf,sourceUrl,JSON.stringify({operator,revision:now,part:i,parts:groups.length,records:part,note:body.note||''}),now));details={kind:'load',region,operator,sourceAsOf,count:records.length,changes,parts:groups.length};statements.push(binding().prepare('INSERT INTO update_runs(id,checked_at,status,details) VALUES(?,?,?,?)').bind(id,now,body.action,JSON.stringify(details)));await binding().batch(statements);return Response.json({saved:true,id,checkedAt:now,details});
 }else if(body.action==='load-observations'){
  const rows=z.array(loadObservationSchema).min(1).max(300).parse(body.observations);if(new Set(rows.map(r=>r.id)).size!==rows.length)throw new Error('부하 관측 ID 중복');
  const previous=await loadObservations(true);const oldMap=new Map(previous.observations.map(r=>[r.id,r]));
  const changes:unknown[]=[];const statements=[];
  for(const r of rows){const old=oldMap.get(r.id);if(r.checkedAt>now.slice(0,10)||r.publicationDate>r.checkedAt||(r.asOf&&r.asOf>r.checkedAt))throw new Error('확인일·공시일·기준일 순서 오류');
   if(old&&((r.asOf||r.publicationDate)<(old.asOf||old.publicationDate)||r.publicationDate<old.publicationDate||r.checkedAt<old.checkedAt))throw new Error('부하 관측 과거 기준일 덮어쓰기 차단');
   if(old&&(old.region!==r.region||old.operator!==r.operator))throw new Error('관측 ID의 권역·사업자 변경 차단');
   if(r.stageBreakdown&&r.valueGW!==null&&Math.abs(r.stageBreakdown.reduce((n,s)=>n+s.valueGW,0)-r.valueGW)>.005)throw new Error('단계별 합계와 원문 총계 불일치');
   const canonical=(v:any):any=>Array.isArray(v)?v.map(canonical):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).filter(k=>k!=='checkedAt').sort().map(k=>[k,canonical(v[k])])):v;const clean=(v:unknown)=>JSON.stringify(canonical(v));
   if(!old||clean(old)!==clean(r))changes.push({id:r.id,region:r.region,operator:r.operator,before:old||null,after:r});
   statements.push(binding().prepare('INSERT INTO datasets(key,kind,region,source_as_of,source_url,payload,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET source_as_of=excluded.source_as_of,source_url=excluded.source_url,payload=excluded.payload,updated_at=excluded.updated_at').bind('load-observation:'+r.id,'load-observation',r.region,r.asOf||r.publicationDate,r.sourceUrl,JSON.stringify(r),now));
  }
  details={count:rows.length,changed:changes.length,changes};const id=crypto.randomUUID();statements.push(binding().prepare('INSERT INTO update_runs(id,checked_at,status,details) VALUES(?,?,?,?)').bind(id,now,body.action,JSON.stringify(details)));await binding().batch(statements);return Response.json({saved:true,id,checkedAt:now,details});
 }else if(body.action==='qualitative-notes'){
  const rows=z.array(qualitativeSchema).min(1).max(150).parse(body.notes);if(new Set(rows.map(r=>r.id)).size!==rows.length)throw new Error('정성 근거 ID 중복');
  const previous=await qualitativeNotes(true),oldMap=new Map(previous.notes.map(r=>[r.id,r]));const changes:unknown[]=[],statements=[];
  for(const r of rows){const old=oldMap.get(r.id);
   if(r.checkedAt>now.slice(0,10)||(r.publicationDate&&r.publicationDate>r.checkedAt))throw new Error('정성 근거 공시일·확인일 순서 오류');
   if(old&&(r.region!==old.region||r.checkedAt<old.checkedAt||(old.publicationDate&&(!r.publicationDate||r.publicationDate<old.publicationDate))))throw new Error('정성 근거 권역 변경·과거 기준일 덮어쓰기 차단');
   const clean=(v:typeof r)=>JSON.stringify({...v,checkedAt:undefined});if(!old||clean(old)!==clean(r))changes.push({id:r.id,region:r.region,before:old||null,after:r});
   statements.push(binding().prepare('INSERT INTO datasets(key,kind,region,source_as_of,source_url,payload,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET source_as_of=excluded.source_as_of,source_url=excluded.source_url,payload=excluded.payload,updated_at=excluded.updated_at').bind('qualitative-note:'+r.id,'qualitative-note',r.region,r.publicationDate||'',r.sourceUrl,JSON.stringify(r),now));
  }
  details={count:rows.length,changed:changes.length,changes};const id=crypto.randomUUID();statements.push(binding().prepare('INSERT INTO update_runs(id,checked_at,status,details) VALUES(?,?,?,?)').bind(id,now,body.action,JSON.stringify(details)));await binding().batch(statements);return Response.json({saved:true,id,checkedAt:now,details});
 }else if(body.action==='named-loads'){
  const rows=z.array(namedLoadSchema).min(1).max(300).parse(body.records);if(new Set(rows.map(r=>r.id)).size!==rows.length)throw new Error('실명 프로젝트 ID 중복');const previous=await namedLoads(true),oldMap=new Map(previous.records.map(r=>[r.id,r]));const changes:unknown[]=[],statements=[];
  for(const r of rows){const old=oldMap.get(r.id);if(r.checkedAt>now.slice(0,10)||(r.asOf&&r.asOf>r.checkedAt)||r.sources.some(s=>s.publishedAt&&s.publishedAt>r.checkedAt))throw new Error('실명 프로젝트 날짜 순서 오류');if(old&&((old.asOf&&(!r.asOf||r.asOf<old.asOf))||r.checkedAt<old.checkedAt||r.region!==old.region))throw new Error('실명 프로젝트 과거자료·권역 변경 차단');
   if(r.matchedProjectId){const p=(await projectsFor(r.region,true)).find(p=>p.id===r.matchedProjectId&&p.kind==='load');if(!p||p.queueId!==r.queueId)throw new Error('공식 원장 연결 검증 실패');}
   const clean=(v:typeof r)=>JSON.stringify({...v,checkedAt:undefined});if(!old||clean(old)!==clean(r))changes.push({id:r.id,region:r.region,before:old||null,after:r});
   statements.push(binding().prepare('INSERT INTO datasets(key,kind,region,source_as_of,source_url,payload,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET source_as_of=excluded.source_as_of,source_url=excluded.source_url,payload=excluded.payload,updated_at=excluded.updated_at').bind('named-load:'+r.id,'named-load',r.region,r.asOf||'',r.sources[0].url,JSON.stringify(r),now));
  }
  details={count:rows.length,changed:changes.length,changes};const id=crypto.randomUUID();statements.push(binding().prepare('INSERT INTO update_runs(id,checked_at,status,details) VALUES(?,?,?,?)').bind(id,now,body.action,JSON.stringify(details)));await binding().batch(statements);return Response.json({saved:true,id,checkedAt:now,details});
 }else if(body.action==='load-sources'){
  const rows=z.array(censusSourceSchema).min(1).max(300).parse(body.sources);if(new Set(rows.map(r=>r.id)).size!==rows.length)throw new Error('수집범위 ID 중복');const oldMap=new Map((await censusSources(true)).sources.map(r=>[r.id,r]));const statements=[];let changed=0;
  for(const r of rows){const old=oldMap.get(r.id);if(r.checkedAt>now.slice(0,10)||old&&r.checkedAt<old.checkedAt)throw new Error('수집범위 확인일 오류');if(old&&old.region!==r.region)throw new Error('수집범위 권역 변경 차단');if(!old||JSON.stringify(old)!==JSON.stringify(r))changed++;statements.push(binding().prepare('INSERT INTO datasets(key,kind,region,source_as_of,source_url,payload,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET source_as_of=excluded.source_as_of,source_url=excluded.source_url,payload=excluded.payload,updated_at=excluded.updated_at').bind('load-source:'+r.id,'load-source',r.region,r.sourceDate||'',r.url,JSON.stringify(r),now));}
  details={count:rows.length,changed};const id=crypto.randomUUID();statements.push(binding().prepare('INSERT INTO update_runs(id,checked_at,status,details) VALUES(?,?,?,?)').bind(id,now,body.action,JSON.stringify(details)));await binding().batch(statements);return Response.json({saved:true,id,checkedAt:now,details});
 }else if(body.action==='policies'){
  const rows=z.array(z.array(z.union([z.string(),z.number(),z.null()])).length(10)).max(80).parse(body.rows);await binding().prepare('INSERT INTO datasets(key,kind,region,source_as_of,source_url,payload,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at,source_as_of=excluded.source_as_of').bind('policies','policies','US',now.slice(0,10),'official multiple',JSON.stringify({rows}),now).run();details={count:rows.length};
  }else if(body.action==='evidence'){
 const evidence=z.record(z.object({title:z.string(),value:z.string(),note:z.string(),source:z.string().url()})).parse(body.evidence);if(regions.some(r=>!evidence[r]))throw new Error('모든 권역 근거 필요');await binding().prepare('INSERT INTO datasets(key,kind,region,source_as_of,source_url,payload,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at,source_as_of=excluded.source_as_of').bind('loadEvidence','evidence','US',now.slice(0,10),'official multiple',JSON.stringify(evidence),now).run();details={regions:regions.length};
 }else if(body.action==='review'){
  details=z.object({sources:z.array(z.object({url:z.string().url(),status:z.enum(['unchanged','updated','unavailable']),note:z.string()})).min(1),note:z.string()}).parse(body.review);for(const region of regions)await snapshot(region,now);
 }else if(body.action==='schedule'){
  const value=z.object({id:z.string(),title:z.string(),timezone:z.string(),schedule:z.string(),enabled:z.boolean()}).parse(body.value);await binding().prepare('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value').bind('schedule',JSON.stringify(value)).run();return Response.json({saved:true,schedule:value});
 }else return Response.json({error:'지원하지 않는 갱신 동작'},{status:400});
 const id=crypto.randomUUID();await binding().prepare('INSERT INTO update_runs(id,checked_at,status,details) VALUES(?,?,?,?)').bind(id,now,body.action,JSON.stringify(details)).run();return Response.json({saved:true,id,checkedAt:now,details});
 }catch(e){console.error('update failed',e);return Response.json({saved:false,error:e instanceof Error?e.message:'갱신 실패'},{status:400})}
}
