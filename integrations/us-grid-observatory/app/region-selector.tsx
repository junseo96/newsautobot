import {REGION_LABELS} from '@/lib/grid-types';

export default function RegionSelector({region,regions,onChange}:{region:string;regions:{id:string}[];onChange:(region:string)=>void}){
 return <div className="region-navigation" role="group" aria-label="분석 권역">
  {regions.map(({id})=><button key={id} type="button" className="region-button" aria-pressed={region===id} onClick={()=>{if(region!==id)onChange(id)}}>{REGION_LABELS[id]||id}</button>)}
 </div>;
}
