import {qualitativeNotes} from '@/lib/qualitative-notes';
import {loadObservations} from '@/lib/load-observations';
import {researchItems} from '@/lib/research-items';
import {binding} from '@/lib/grid-db';
import seed from '@/data/seed.json';
export async function GET(){
 const [qualitative,load]=await Promise.all([qualitativeNotes(),loadObservations()]);let policies=seed.policies,policiesAvailable=false,history:unknown[]=[];
 try{const p=await binding().prepare('SELECT payload FROM datasets WHERE key=?').bind('policies').first<{payload:string}>();if(p)policies=JSON.parse(p.payload).rows;policiesAvailable=true;
 const h=await binding().prepare('SELECT checked_at,details FROM update_runs WHERE status=? ORDER BY checked_at DESC LIMIT 24').bind('qualitative-notes').all<{checked_at:string;details:string}>();history=h.results.map(r=>({checkedAt:r.checked_at,...JSON.parse(r.details)}));}catch{}
 return Response.json({items:researchItems(qualitative.notes,load.observations,policies),notes:qualitative.notes,history,storageAvailable:qualitative.storageAvailable&&load.storageAvailable&&policiesAvailable},{headers:{'Cache-Control':'private, max-age=60'}});
}
