import {namedLoads} from '@/lib/named-loads';
import {binding} from '@/lib/grid-db';
export async function GET(){const data=await namedLoads();let history:unknown[]=[];try{const rows=await binding().prepare('SELECT checked_at,details FROM update_runs WHERE status=? ORDER BY checked_at DESC LIMIT 24').bind('named-loads').all<{checked_at:string;details:string}>();history=rows.results.map(r=>({checkedAt:r.checked_at,...JSON.parse(r.details)}))}catch{}return Response.json({...data,history},{headers:{'Cache-Control':'private, max-age=60'}})}
