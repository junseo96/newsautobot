import {projectsFor,compactLoadProject} from '@/lib/grid-db';
import {censusSources} from '@/lib/load-census';
export async function GET(){const [projects,coverage]=await Promise.all([projectsFor(),censusSources()]);return Response.json({...coverage,records:projects.filter(p=>p.kind==='load').map(compactLoadProject)},{headers:{'Cache-Control':'private,max-age=60'}})}
