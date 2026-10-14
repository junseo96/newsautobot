import {z} from 'zod';
const date=z.string().regex(/^\d{4}-\d{2}-\d{2}$/).refine(v=>!Number.isNaN(Date.parse(v))&&new Date(v).toISOString().slice(0,10)===v);
const text=z.string().min(1).max(4000);
const source=z.object({id:text,title:text,url:z.string().url().refine(v=>v.startsWith('https://')),publishedAt:date.nullable()});
export const namedLoadSchema=z.object({
 id:z.string().min(1).max(180),name:text,aliases:z.array(text).max(20),region:z.enum(['CAISO','ERCOT','ISO-NE','MISO','NYISO','PJM','SPP','West','Southeast']),regionBasis:text,
 industry:text.optional(),industryEvidence:text.optional(),lifecycle:z.enum(['planned','construction','partial-operation','operating','withdrawn','cancelled','unknown']).optional(),location:text,participants:z.array(z.object({role:text,name:text})).min(1).max(12),utility:text.nullable(),powerRoute:z.enum(['grid','onsite','mixed','unknown']),
 capacities:z.array(z.object({mw:z.number().finite().nonnegative(),basis:text,sourceId:text})).max(10),
 gridRequestMW:z.number().finite().nonnegative().nullable(),queueId:text.nullable(),matchedProjectId:text.nullable(),
 statusSummary:text,milestones:z.array(z.object({gate:z.enum(['프로젝트','전력 확보','인허가','공사','통전']),status:z.enum(['확인','조건부','미확보']),detail:text,sourceId:text.nullable()})).min(1).max(10),
 gaps:z.array(text).min(1).max(15),sources:z.array(source).min(1).max(15),asOf:date.nullable(),checkedAt:date,additive:z.literal(false)
}).superRefine((r,ctx)=>{const ids=new Set(r.sources.map(s=>s.id));if(ids.size!==r.sources.length||r.capacities.some(c=>!ids.has(c.sourceId))||r.milestones.some(m=>m.sourceId&&!ids.has(m.sourceId)))ctx.addIssue({code:z.ZodIssueCode.custom,message:'근거 sourceId 연결 오류'});if(r.gridRequestMW!==null&&!r.queueId)ctx.addIssue({code:z.ZodIssueCode.custom,message:'접속신청 MW의 공식 큐 연결 필요'});});
export type NamedLoad=z.infer<typeof namedLoadSchema>;
