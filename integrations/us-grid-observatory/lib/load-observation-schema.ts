import {z} from 'zod';
export const LOAD_STAGE_LABELS={request:'요청·협의',study:'기술 검토',contract:'계약',construction:'공사',energized:'가동·접속',forecast:'부하 전망',mixed:'단계 혼합'};
const date=z.string().regex(/^\d{4}-\d{2}-\d{2}$/).refine(v=>!Number.isNaN(Date.parse(v))&&new Date(v).toISOString().slice(0,10)===v);
const period=z.union([date,z.string().regex(/^\d{4}-(0[1-9]|1[0-2])$/)]);
const required=z.string().min(1).max(4000);
export const loadObservationSchema=z.object({
 id:z.string().min(1).max(200),region:z.enum(['CAISO','ERCOT','ISO-NE','MISO','NYISO','PJM','SPP','West','Southeast']),
 operator:required,metricLabel:required,valueGW:z.number().finite().nonnegative().nullable(),valueQualifier:z.enum(['=','~','>','>=']).default('='),
 stageClass:z.enum(['request','study','contract','construction','energized','forecast','mixed']),asOf:period.nullable(),asOfNote:z.string().max(1000).optional(),publicationDate:date,
 sourceUrl:z.string().url().refine(v=>new URL(v).protocol==='https:'),sourceTitle:required,evidenceText:required,scope:required,includesEnergized:z.boolean().nullable(),additive:z.literal(false),
 collectionMethod:required,nextAction:required,remainingGap:required,checkedAt:date,
 parentId:z.string().optional(),metricBasis:z.string().optional(),targetYear:z.number().int().optional().nullable(),
 stageBreakdown:z.array(z.object({stageClass:z.enum(['request','study','contract','construction','energized','forecast','mixed']),stage:required,valueGW:z.number().finite().nonnegative(),projectCount:z.number().int().nonnegative().nullable().optional(),criterion:required})).max(20).optional()
});
export type LoadObservation=z.infer<typeof loadObservationSchema>;
