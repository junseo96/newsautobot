import initial from '@/data/qualitative-notes.json';
import {binding} from './grid-db';
import {qualitativeSchema,type QualitativeNote} from './qualitative-schema';
export const initialQualitativeNotes=initial as QualitativeNote[];
export async function qualitativeNotes(strict=false){
 const values=new Map(initialQualitativeNotes.map(r=>[r.id,r]));let storageAvailable=false;
 try{const rows=await binding().prepare('SELECT payload FROM datasets WHERE kind=?').bind('qualitative-note').all<{payload:string}>();
  for(const row of rows.results){const r=qualitativeSchema.parse(JSON.parse(row.payload)),old=values.get(r.id);if(!old||r.checkedAt>=old.checkedAt)values.set(r.id,r)}storageAvailable=true;
 }catch(e){if(strict)throw e}
 return {notes:[...values.values()],storageAvailable};
}
