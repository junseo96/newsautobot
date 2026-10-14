import initial from '@/data/load-observations.json';
import {binding,projectsFor} from '@/lib/grid-db';
import seed from '@/data/seed.json';
import type {LoadObservation} from './load-observation-schema';
export const initialLoadObservations=initial as LoadObservation[];
export async function loadObservations(strict=false){
 const values=new Map(initialLoadObservations.map(r=>[r.id,r]));let stored=false;
 try{const rows=await binding().prepare('SELECT payload FROM datasets WHERE kind=?').bind('load-observation').all<{payload:string}>();for(const row of rows.results){const r=JSON.parse(row.payload) as LoadObservation;const old=values.get(r.id);if(!old||(r.asOf||r.publicationDate)>=(old.asOf||old.publicationDate))values.set(r.id,r)}stored=true}catch(e){if(strict)throw e}
 return {observations:[...values.values()],storageAvailable:stored};
}
export async function loadCoverage(){const projects=await projectsFor();return seed.regions.map(region=>{const rows=projects.filter(p=>p.kind==='load'&&p.region===region.id);const valid=rows.filter(p=>p.include===1&&!['W','G8'].includes(p.stage)&&typeof p.mw==='number');return{region:region.id,records:rows.length,capacityKnown:rows.filter(p=>typeof p.mw==='number').length,stageKnown:rows.filter(p=>!['GU','GN','GC','GS'].includes(p.stage)).length,eligibleRecords:valid.length,eligibleGW:valid.length?valid.reduce((s,p)=>s+Number(p.mw),0)/1000:null}})}
