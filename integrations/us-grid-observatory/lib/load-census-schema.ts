import {z} from 'zod';
const text=z.string().min(1).max(6000),date=z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
export const censusSourceSchema=z.object({id:text,region:z.enum(['CAISO','ERCOT','ISO-NE','MISO','NYISO','PJM','SPP','West','Southeast','AK','HI','US']),operator:text,title:text,universe:text,selection:text,coverage:z.enum(['full-register','filtered-register','aggregate','case','not-public','access-failed','not-reviewed']),sourceRows:z.number().int().nonnegative().nullable(),loadedRows:z.number().int().nonnegative().nullable(),sourceDate:z.string().nullable(),sourceDateMeaning:text,checkedAt:date,url:z.string().url().refine(s=>s.startsWith('https://')),gaps:z.array(text).min(1),nextAction:text});
export type CensusSource=z.infer<typeof censusSourceSchema>;
