import seed from '@/data/load-sources.json';
import {binding} from './grid-db';
import {censusSourceSchema,type CensusSource} from './load-census-schema';
export async function censusSources(strict=false){const map=new Map((seed as CensusSource[]).map(s=>[s.id,s]));let storageAvailable=false;try{const r=await binding().prepare('SELECT payload FROM datasets WHERE kind=?').bind('load-source').all<{payload:string}>();for(const v of r.results){const p=censusSourceSchema.parse(JSON.parse(v.payload)),old=map.get(p.id);if(!old||p.checkedAt>=old.checkedAt)map.set(p.id,p)}storageAvailable=true}catch(e){if(strict)throw e}return{sources:[...map.values()],storageAvailable}}
