import initial from '@/data/named-loads.json';
import {binding} from './grid-db';
import {namedLoadSchema,type NamedLoad} from './named-load-schema';
export const initialNamedLoads=initial as NamedLoad[];
export async function namedLoads(strict=false){const map=new Map(initialNamedLoads.map(r=>[r.id,r]));let storageAvailable=false;
 try{const rows=await binding().prepare('SELECT payload FROM datasets WHERE kind=?').bind('named-load').all<{payload:string}>();for(const row of rows.results){const r=namedLoadSchema.parse(JSON.parse(row.payload)),old=map.get(r.id);if(!old||(r.asOf||'')>=(old.asOf||''))map.set(r.id,r)}storageAvailable=true}catch(e){if(strict)throw e}
 return{records:[...map.values()],storageAvailable};
}
