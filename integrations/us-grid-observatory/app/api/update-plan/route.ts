import plan from '@/data/update-plan.json';
import seed from '@/data/seed.json';
export function GET(){return Response.json({...plan,stages:seed.stages})}
