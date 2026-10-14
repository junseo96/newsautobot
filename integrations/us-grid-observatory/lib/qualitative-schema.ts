import {z} from 'zod';
const date=z.string().regex(/^\d{4}-\d{2}-\d{2}$/).refine(v=>!Number.isNaN(Date.parse(v))&&new Date(v).toISOString().slice(0,10)===v);
const prose=z.string().min(1).max(4000);
export const qualitativeSchema=z.object({
 id:z.string().min(1).max(200),region:z.enum(['US','CAISO','ERCOT','ISO-NE','MISO','NYISO','PJM','SPP','West','Southeast']),
 category:z.enum(['공개 범위','접속 절차','정책 상태','해석 기준']),title:prose,summary:prose,
 verifiedFacts:z.array(prose).min(1).max(12),interpretation:prose,limitations:prose,nextCheck:prose,
 sourceUrl:z.string().url().refine(v=>v.startsWith('https://')),sourceTitle:prose,
 publicationDate:date.nullable(),checkedAt:date,status:z.enum(['확인','조건부','공시 불일치'])
});
export type QualitativeNote=z.infer<typeof qualitativeSchema>;
