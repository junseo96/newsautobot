import {newsEvent,regions,gates} from '@/lib/newsflow-schema';
import {projectsFor} from '@/lib/grid-db';
import {z} from 'zod';
async function database(){const {env}=await import('cloudflare:workers');if(!env.DB)throw new Error('Newsflow database unavailable');return env.DB;}
export async function POST(request:Request){
  // Owner-private Sites authenticates browser and approved service access.
  const origin=request.headers.get('origin');if(origin&&origin!==new URL(request.url).origin)return Response.json({error:'cross_origin'},{status:403});
  if(Number(request.headers.get('content-length')||0)>400000)return Response.json({error:'body_too_large'},{status:413});
  const body=await request.text();if(body.length>400000)return Response.json({error:'body_too_large'},{status:413});
  let events;try{events=z.object({events:z.array(newsEvent).min(1).max(20)}).strict().parse(JSON.parse(body)).events}catch{return Response.json({error:'invalid_evidence_contract'},{status:400})}
  const db=await database();const at=new Date().toISOString();const commands=[];const matches=new Map<string,Awaited<ReturnType<typeof projectsFor>>>();
  for(const e of events){
    let matched:string|null=null;let basis='unresolved';
    if((e.queue_id||e.official_project_id)&&!['Unknown','US'].includes(e.region)){
      if(!matches.has(e.region))matches.set(e.region,await projectsFor(e.region));
      const rows=matches.get(e.region)!.filter(p=>(!e.state||p.state===e.state)&&(['generation','storage'].includes(e.asset_kind)?p.kind==='generation':e.asset_kind==='load'?p.kind==='load':true)&&
        ((!!e.queue_id&&p.queueId===e.queue_id)||(!!e.official_project_id&&(p.officialNeedId===e.official_project_id||p.transmissionProjectId===e.official_project_id))));
      if(rows.length===1){matched=rows[0].id;basis='exact_official_id'}else if(rows.length>1)basis='ambiguous_official_id';
    }
    if(e.asset_kind==='policy')basis='regional_policy_not_project_approval';
    const payload={...e,matched_project_id:matched,match_basis:basis};
    commands.push(db.prepare('INSERT INTO grid_assets(id,name,kind,region,state,queue_id,official_project_id,updated_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at').bind(e.asset_id,e.asset_name,e.asset_kind,e.region,e.state,e.queue_id,e.official_project_id,at));
    commands.push(db.prepare('INSERT INTO grid_events(id,asset_id,region,gate,status,published_at,observed_at,payload,telegram_status,dashboard_status,matched_project_id,ingested_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET asset_id=excluded.asset_id,region=excluded.region,gate=excluded.gate,status=excluded.status,payload=excluded.payload,telegram_status=excluded.telegram_status,matched_project_id=excluded.matched_project_id,ingested_at=excluded.ingested_at').bind(e.id,e.asset_id,e.region,e.gate,e.status,e.published_at,e.observed_at,JSON.stringify(payload),e.telegram.status,'reflected',matched,at));
  }
  commands.push(db.prepare('INSERT INTO grid_sync_runs(id,at,status,details) VALUES(?,?,?,?)').bind(crypto.randomUUID(),at,'complete',JSON.stringify({accepted:events.length,ids:events.map(e=>e.id)})));
  await db.batch(commands);
  return Response.json({accepted_ids:events.map(e=>e.id),ingested_at:at},{headers:{'Cache-Control':'no-store'}});
}
export async function GET(request:Request){
  const p=new URL(request.url).searchParams;const clauses:string[]=[];const values:string[]=[];
  // Legacy facts lack explicit project/gate IDs and are opt-in context, not
  // newly completed milestone rows. No loss: the history stays queryable.
  if(p.get('context')!=='1')clauses.push("json_extract(payload,'$.provenance') <> 'legacy_verified_context'");
  for(const [field,column,allowed] of [['region','region',regions],['gate','gate',gates]] as const){const v=p.get(field);if(v&&v!=='all'){if(!allowed.includes(v as never))return Response.json({error:'invalid_filter'},{status:400});clauses.push(column+'=?');values.push(v)}}
  for(const [field,column] of [['asset','asset_id'],['project','matched_project_id']] as const){const v=p.get(field);if(v){if(v.length>200)return Response.json({error:'invalid_filter'},{status:400});clauses.push(column+'=?');values.push(v)}}
  const limit=Math.min(100,Math.max(1,Number(p.get('limit'))||40));const offset=Math.max(0,Math.min(100000,Number(p.get('offset'))||0));
  const where=clauses.length?' WHERE '+clauses.join(' AND '):'';const db=await database();
  const rows=await db.prepare('SELECT payload,ingested_at FROM grid_events'+where+' ORDER BY julianday(COALESCE(published_at,observed_at)) DESC,id LIMIT ? OFFSET ?').bind(...values,limit,offset).all<{payload:string;ingested_at:string}>();
  const count=await db.prepare('SELECT COUNT(*) AS count FROM grid_events'+where).bind(...values).first<{count:number}>();
  const sync=await db.prepare('SELECT at,status,details FROM grid_sync_runs ORDER BY at DESC LIMIT 1').first();
  let gateSummary:unknown[]=[];
  const identity=p.get('asset')||p.get('project');
  if(identity){
    const all=await db.prepare('SELECT payload FROM grid_events WHERE '+(p.get('asset')?'asset_id':'matched_project_id')+'=? ORDER BY julianday(COALESCE(published_at,observed_at)) DESC,id').bind(identity).all<{payload:string}>();
    const facts=all.results.map(r=>JSON.parse(r.payload));
    gateSummary=gates.filter(g=>!['unknown','policy'].includes(g)).map(g=>{
      const selected=facts.filter(e=>e.gate===g);const latest=selected[0];
      if(!latest)return {gate:g,status:'unknown',published_at:null,event_id:null,remaining_requirements:['원문 근거 미확보']};
      const sameDay=selected.filter(e=>(e.published_at||'').slice(0,10)===(latest.published_at||'').slice(0,10));
      const conflict=new Set(sameDay.map(e=>e.status)).size>1;
      return {gate:g,status:conflict?'conflicting':latest.status,published_at:latest.published_at,event_id:latest.id,remaining_requirements:latest.remaining_requirements};
    });
  }
  return Response.json({events:rows.results.map(r=>({...JSON.parse(r.payload),ingested_at:r.ingested_at})),total:count?.count||0,limit,offset,last_sync:sync,gate_summary:gateSummary},{headers:{'Cache-Control':'private,no-store'}});
}
