"""Research evidence package. No Site code is touched by this script."""
import json,pathlib,collections
P=pathlib.Path(__file__).parent
CHECKED='2026-10-03'
def save(n,x): (P/n).write_text(json.dumps(x,ensure_ascii=False,indent=2))
def source(url,title,publishedAt=None,asOf=None,note=None):
 return dict(url=url,title=title,publishedAt=publishedAt,asOf=asOf,checkedAt=CHECKED,note=note)
portal='https://www.cpuc.ca.gov/industries-and-topics/electrical-energy/infrastructure/energization/energization-data-reporting-requirements-and-data-reporting-template'
inventory=json.loads((P/'energization-inventory.json').read_text())
byutility={s['utility']:s for s in inventory['sources']}
coverage=[]
def cover(utility,state,granularity,sources,gap,**kw):
 coverage.append(dict(utility=utility,state=state,checkedAt=CHECKED,granularity=granularity,sources=sources,remainingGap=gap,allCustomersSurveyed=False,**kw))
cover('CAISO','CA','Process and stakeholder policy; no load-request row register located in examined sources',[
 source('https://stakeholdercenter.caiso.com/StakeholderInitiatives/Large-loads','CAISO Large loads stakeholder initiative',None,None,'Draft-final proposal September 24, 2026; October 1 discussion and October 15 comments. Not a list of customers.'),
 source('https://www.caiso.com/documents/issue-paper-large-load-consideration-jan-20-2026.pdf','Large Load Considerations issue paper','2026-01-20')],
 'CAISO generation interconnection queue is not a retail load queue. Customer requests sit with serving utilities; examined stakeholder documents do not enumerate them.',coverageStatus='process_only',importedRows=0)
cover('PG&E','CA','Full public September 2025 service-request workbook; industrial subset extracted',[
 source(byutility['PG&E']['url'],'September 2025 biannual energization workbook','2025-09-30','2025-06-30'),
 source('https://www.cpuc.ca.gov/-/media/cpuc-website/divisions/energy-division/documents/infrastructure/energization/pge-biannual-energization-report-public_20250930.pdf','September 2025 narrative','2025-09-30','2025-06-30'),
 source('https://docs.cpuc.ca.gov/PublishedDocs/Efile/G000/M604/K023/604023792.PDF','March 2026 narrative','2026-04-01','2025-12-31'),
 source('https://docs.cpuc.ca.gov/PublishedDocs/Efile/G000/M604/K025/604025633.PDF','Notice of availability of March 2026 public workbook','2026-04-02',None,'Directs to PG&E archive, case R.24-01-018, filing date March 31, 2026'),
 source('https://pgera.azurewebsites.net/Regulation/search','PG&E public regulatory archive'),source(portal,'CPUC energization publication index')],
 'Latest March 2026 narrative was obtained but accompanying public XLSX was not retrieved through archive search. The extracted June 2025 snapshot must not be presented as current queue. September 2026 not linked on examined CPUC portal. Public customer names, cities and requested capacity missing; many ordinary commercial entries cannot be classified as high load.',coverageStatus='public_register_partial_vintage',fullWorkbookRows=55284,tariffRows=25207,mpuRows=30077,selectedRows=196,selectedByStage={'in_progress':133,'energized':35,'cancelled':28},highLoadSelection='Explicit New Industrial classification; capacity is undisclosed for all selected rows. Not 196 confirmed >=10 MW customers.',latestRegisterAsOf='2025-06-30',latestNarrativeAsOf='2025-12-31')
cover('SCE','CA','Narrative and confidentiality filing; public spreadsheet named but not reliably acquired',[
 source('https://docs.cpuc.ca.gov/PublishedDocs/Efile/G000/M604/K030/604030059.PDF','March 2026 narrative and mixed-media Attachment A','2026-04-01','2025-12-31'),
 source('https://docs.cpuc.ca.gov/PublishedDocs/Efile/G000/M604/K002/604002989.PDF','Motion for confidential treatment of energization data','2026-04-01'),
 source('https://www.cpuc.ca.gov/-/media/cpuc-website/divisions/energy-division/documents/infrastructure/energization/scepubliceet-september-2025-report20250930ver2.xlsx','CPUC SCE September 2025 workbook link','2025-09-30','2025-06-30','Repeated requests returned zero-byte body'),
 source(portal,'CPUC energization publication index')],
 'March 2026 public Attachment A is described as a mixed-media docket filing; no retrievable XLSX obtained. Official September 2025 publiceet link yielded empty response. Alternative SCE-labeled URL actually contains SDG&E sheets/notes and was excluded. Zero imported rows means missing acquisition, not no large customers.',coverageStatus='register_exists_acquisition_gap',importedRows=0)
cover('SDG&E','CA','Full public March 2026 service-request workbook; unvalidated nonresidential large raw-number candidates extracted',[
 source(byutility['SDG&E']['url'],'Public Attachment B, March 31 2026 energization workbook','2026-04-01','2025-12-31'),
 source('https://docs.cpuc.ca.gov/PublishedDocs/Efile/G000/M603/K533/603533572.PDF','March 2026 narrative','2026-04-01','2025-12-31','PDF pages 7–8 explain Step 8 and preliminary capacity quality limits'),
 source('https://www.sdge.com/rates-and-regulations/proceedings/Order-Instituting-Rulemaking-to-Establish-Energization-Timelines','SDG&E official proceeding index')],
 'IDs and city are redacted. Commercial is not an industry classification. Utility warns requested kW can be inflated or wrongly entered amperes and remain uncorrected after formal load study. No MW totals or unique-customer counts can be inferred. Closed may mean ready-for-service/first-meter setting rather than full-site commercial operation. September 2026 data not acquired.',coverageStatus='public_register_with_material_quality_limits',fullWorkbookRows=29337,tariffRows=19694,mpuRows=9643,selectedRows=58,selectedByStage={'ongoing':27,'closed':31},excludedResidentialRawAnomalies=225,highLoadSelection='Nonresidential raw requested kW >=10000; 58 Commercial intake candidates. All normalized MW fields remain null.',latestRegisterAsOf='2025-12-31')
cover('LADWP','CA','Service-planning instructions plus named port infrastructure program',[
 source('https://www.ladwp.com/construction-services/electric-services-faqs','Electric services construction FAQs'),
 source('https://www.ladwp.com/events/2026-09-10/power-service-planning-design-process','Power service planning and design process event','2026-09-10'),
 source('https://portoflosangeles.org/commission/agenda-archive-and-videos/agendas/2026/05282026-regular-agenda','Port board agenda including ZEPEO','2026-05-28')],
 'No public all-customer service-request register located in examined service-planning pages. Port MVA figures are an aggregate infrastructure program, not identified utility queue requests.',coverageStatus='process_and_named_project',importedRegisterRows=0)
cover('SMUD','CA','Official large-load aggregate: two potential projects above 50 MW',[
 source('https://www.smud.org/Corporate/About-us/Reliability/Large-electrical-load-project-growth','Large electrical load project growth',None,None,'Current page says two early-stage potential projects, no approved large-load projects, policy expected early 2027'),
 source('https://www.smud.org/Corporate/Do-Business-with-SMUD/Commercial-Development','Commercial development process')],
 'Customer identities/locations withheld for privacy and NDAs. Two potential requests are feasibility/transmission-study stage and not two confirmed DCs. No row-level service register obtained.',coverageStatus='aggregate_only',aggregatePotentialProjects=2,aggregateThresholdMW=50,importedRegisterRows=0)
cover('Chugach Electric','AK','Commercial application/checklist process',[
 source('https://www.chugachelectric.com/services/construction-and-engineering','Construction and engineering'),
 source('https://www.chugachelectric.com/system/files/Information%20Checklist%20for%20mock.pdf','Engineering checklist')],
 'No public customer request queue or comprehensive load register located in examined construction materials.',coverageStatus='process_only',importedRegisterRows=0)
cover('Golden Valley Electric Association','AK','Board aggregate of existing industrial accounts',[
 source('https://www.gvea.com/news-releases/gvea-board-meeting-recap-august-13-2026/','August 13 board recap','2026-08-13',None,'2025 six industrial accounts used 44 percent of energy; existing sales is not a pending-load register')],
 'Individual names/request MW/stages not disclosed in examined recap; no request register obtained. Existing six industrial customers must not be counted as six new requests.',coverageStatus='aggregate_only',importedRegisterRows=0)
cover('Matanuska Electric Association','AK','Service request instructions and large-load member consultation',[
 source('https://www.mea.coop/news/mea-seeking-member-input-on-data-centers-through-member-survey','Large-load/data-center member survey'),
 source('https://www.mea.coop/account-services/sign-up-for-service','Service initiation'),
 source('https://www.mea.coop/major-projects/2026-capital-improvement-projects','2026 capital improvement projects')],
 'Consultation and utility construction program do not expose customer identities or project-level requested MW; no public request register obtained.',coverageStatus='process_only',importedRegisterRows=0)
cover('Homer Electric Association','AK','Service instructions and aggregate applications reporting',[
 source('https://www.homerelectric.com/member-services/new-construction/new-home-business/','New home/business electric service'),
 source('https://www.homerelectric.com/2026/09/september-2026-monthly-ceo-report/','September 2026 CEO report','2026-09')],
 'Aggregate application chart cannot identify high-load industrial customers; no row register obtained.',coverageStatus='aggregate_and_process',importedRegisterRows=0)
cover('Hawaiian Electric group (Oahu, Maui Electric, Hawaii Electric Light)','HI','Group large-customer service process',[
 source('https://www.hawaiianelectric.com/electrical-services/upgrade-modify-or-install-service','Upgrade, modify or install service'),
 source('https://www.hawaiianelectric.com/documents/electrical_services/large_customer_NSC_brochure_web.pdf','Large Customer New Service Connection brochure')],
 'Group public instructions cover applications and engineering, but no named all-customer large-load request register located. This is a shared process check, not independent exhaustive docket surveys of all three utilities.',coverageStatus='group_process_only',importedRegisterRows=0)
cover('Kauai Island Utility Cooperative','HI','Service application and installation manual',[
 source('https://kiuc.coop/start-or-stop-service','Start or stop service'),
 source('https://kiuc.coop/sites/default/files/2025-03/kiuc_service_installation_manual_rev2020-12.pdf','Service installation manual',None,'2020-12')],
 'No public all-customer high-load request register located in examined materials; no inference of zero high-load projects.',coverageStatus='process_only',importedRegisterRows=0)
cover('Other California municipal utilities and smaller IOUs','CA','Not individually examined in this assigned utility scope',[],
 'Silicon Valley Power, IID, Burbank, Glendale, Pasadena, Anaheim, Riverside, Modesto/Turlock, Liberty, PacifiCorp, Bear Valley and other utilities remain outside this assigned six-utility examination. Near-census California claim would require them.',coverageStatus='not_examined',importedRegisterRows=0)
cover('Other Alaska municipal, cooperative and village utilities','AK','Not individually examined',[],
 'Only four named Railbelt utility public-source checks above. Southeast and rural/village utilities and off-grid industrial owners not comprehensively surveyed. Donlin named evidence is not a utility register.',coverageStatus='not_examined',importedRegisterRows=0)
save('coverage-inventory.json',{'checkedAt':CHECKED,'coverageStatement':'14 coverage entries; 12 examined entity/group entries and 2 explicit unexamined residual categories. No state or utility is claimed fully censused. Public-source absence is not proof of zero projects.','entries':coverage})

projects=[]
def project(id,name,state,operator,industry,mw,basis,stage,stageAsOf,sources,**kw):
 projects.append(dict(id=id,name=name,state=state,operator=operator,industry=industry,mw=mw,gridRequestMW=None,capacityBasis=basis,stage=stage,stageAsOf=stageAsOf,checkedAt=CHECKED,recordType='named_project_evidence',queueId=None,additive=False,sources=sources,**kw))
project('CA-AVH1','Antelope Valley Hydrogen 1','CA','Utility not established; primarily behind-the-meter generation','Hydrogen electrolysis',162,'County application proposes up to 162 MW electrolyzer equipment; not grid-request MW','Land-use applications received; current developer continues marketing, later permit status unverified','2024-11-25',[
 source('https://planning.lacounty.gov/wp-content/uploads/2024/12/DRP_PlanningArea_Countywide_25-11-2024_06-00-14.pdf','LA County application list, pages 17–22','2024-11-25','2024-11-25','RPAP2024006028/6029/6030 received 2024-11-22; single project RPPL2024000110'),
 source('https://novohydrogen.com/news/california-arches-hub-secures-nations-first-federal-funding-for-renewable-clean-hydrogen/','Developer ARCHES update','2024-08-06',None,'Describes 182 MW electrolysis plus 235 MW onsite PV, inconsistent with later county 162 MW application'),
 source('https://novohydrogen.com/antelope-valley-hydrogen-1/','Developer project page',None,None,'Page includes incompatible 182 MW and older 300 MW sections; no single current value can be established')],
 capacityAsOf='2024-11-25',capacityAlternativeDisclosures=[{'value':182,'unit':'MW','date':'2024-08-06','basis':'Developer electrolyzer design'},{'value':300,'unit':'MW','date':None,'basis':'Conflicting older duplicate section on undated developer page'}],gridSupplyRoute='behind_the_meter_primary',confirmedActiveUtilityRequest=False,includeInPendingGridMW=False,note='Three land-use application rows are one hydrogen project. 240 MW county solar proposal is generation, not load. Electrolyzer ratings are explicitly electrical equipment, but proposed design and grid-service request differ.')
project('CA-POLA-ZEPEO','Port of Los Angeles Zero-Emission Port Electrification and Operations (ZEPEO)','CA','LADWP','Port cargo-handling electrification',None,'Additional electrical infrastructure capacity in MVA; no power-factor conversion','Environmental review adopted; MOU approval proposed in examined agenda','2026-05-28',[
 source('https://portoflosangeles.org/commission/agenda-archive-and-videos/agendas/2026/05282026-regular-agenda','Port board agenda item 7','2026-05-28','2026-05-28','MOU scope: additional 213 MVA by 2030 and additional 306 MVA by 2035'),
 source('https://portoflosangeles.org/environment/environmental-documents','Port environmental documents',None,'2026-05-28','ZEPEO adopted May 28, 2026; LADWP certified IS/MND March 24, 2026; SCH2025120795'),
 source('https://portoflosangeles.org/environment/air-quality/cooperative-agreement','Port-LADWP cooperative agreement overview',None,None,'Undated overview has additional 200 MVA; dated MOU scope retained separately')],
 requestedMVA=213,capacityAsOf='2026-05-28',capacityMilestones=[{'year':2030,'value':213,'unit':'MVA','basis':'additional medium-voltage power at 34.5 kV'},{'year':2035,'value':306,'unit':'MVA','basis':'additional capacity wording in source; do not sum with 213 without engineering scope'}],confirmedActiveUtilityRequest=False,includeInPendingGridMW=False,recordIsUniqueCustomer=False,note='Port-wide infrastructure program can overlap individual terminal expansions. Not one customer queue row; not 200/213/306 MW. July 14 anticipated LADWP MOU vote not independently verified.')
project('CA-APMT-PIER400','APM Terminals Pier 400 grid-capacity expansion','CA','LADWP','Container terminal electrification',18,'Target total grid capacity grows from 7 MW to 18 MW; not an 18 MW incremental request','Grid expansion described as underway; fleet partly operating, full 18 MW energization unverified',None,[
 source('https://portelectrification.com/case-studies/pier-400','ZEPA member-coordinated Pier 400 case study',None,None,'Sources named APM Terminals, Kalmar, Orange EV and Port of Los Angeles; figures footer says mid-2025 but body discusses 2025 volumes and earlier this year')],
 capacityAsOf=None,sourceAsOfText='Figures as of mid-2025; internal date inconsistency in live page',existingCapacityMW=7,targetCapacityMW=18,confirmedActiveUtilityRequest=False,includeInPendingGridMW=False,note='Industry alliance case study published in coordination with participating companies; exact publication and full grid completion date unavailable. Current fleet operation is not proof the 18 MW grid expansion is complete. May overlap ZEPEO infrastructure.')
project('AK-DONLIN','Donlin Gold mine','AK','Planned on-site power supply','Gold mining and processing',153,'Average running electrical load in 2018 final EIS design; not 227 MW generation capacity or a utility request','Bankable feasibility study and financing preparation; final investment decision remains prospective','2026-08-11',[
 source('https://www.donlingoldseis.com/final-eis-2018/Executive%20Summary_FEIS.pdf','US Army Corps Donlin final EIS executive summary, page 16','2018-04',None,'153 MW average running load; planned 227 MW generation includes redundancy'),
 source('https://novagold.com/novagold-paulson-announce-the-appointment-of-endeavour-financial-and-macquarie-capital-as-financial-advisors-to-the-donlin-gold-project/','Developer financing-adviser appointment','2026-08-11','2026-08-11','BFS and workstreams precede final investment decision')],
 capacityAsOf='2018-04',gridSupplyRoute='onsite_generation',confirmedActiveUtilityRequest=False,includeInPendingGridMW=False,note='Historic engineered load retained with vintage; 2026 BFS may revise design. Off-grid proposed mine must not be counted in Railbelt utility load queue or presented as operating/construction committed.')
project('CA-GOOGLE-DISK-DRIVE','Google 5079 Disk Drive, San Jose','CA','PG&E','Data center',250,'Forecast retail electric demand at full build, 230 kV','Preliminary engineering study completed; exceptional-case agreement regulatory approval pending, held to October 8','2026-10-02',[
 source('https://docs.cpuc.ca.gov/PublishedDocs/Published/G000/M607/K718/607718746.PDF','Draft Resolution E-5455','2026-07-16',None,'Page 3 application March 3, 2025; latest PES December 2025; 250 MW at full build; AL7785-E filed December 18, 2025'),
 source('https://docs.cpuc.ca.gov/PublishedDocs/Published/G000/M622/K069/622069835.pdf','October 8, 2026 CPUC agenda, pages 3–4','2026-10-02','2026-10-02','Item 2 remains proposed; prior holds July 16, August 13, September 3 and September 17'),
 source('https://docs.cpuc.ca.gov/PublishedDocs/Published/G000/M619/K318/619318894.PDF','September 17 final hold list','2026-09-15','2026-09-17')],
 utilityAdviceLetter='7785-E',identifierType='Official advice-letter identifier, not queue ID',capacityAsOf='2026-07-16',confirmedActiveUtilityRequest=True,includeInPendingGridMW=True,targetInService='2028-12',targetConstructionStart='2027-01',note='Draft language saying approves is a proposed outcome, not an approval. Official October agenda confirms not adopted as of this research date. Target dates are applicant schedule, not completed milestones.')
projects[-1]['gridRequestMW']=250
save('named-project-evidence.json',{'checkedAt':CHECKED,'count':len(projects),'nonDataCenterCount':4,'confirmedPendingUtilityRequestCount':1,'projects':projects})

save('research-notes.json',{
 'checkedAt':CHECKED,'registerRowsExtracted':254,'registerRowsActiveByOriginalTab':160,'allNormalizedRegisterMWNull':True,
 'rawRegisterRowsInspected':84621,'tariffRowsInspected':44901,'mpuRowsOutsideScope':39720,
 'selection':'All tariff rows screened for >=10000 raw requested kW or explicit industrial/large-load class. Residential and MPU excluded; ordinary Commercial with unknown/small capacity is not automatically industrial. Source XLSX is retained intact.',
 'countsAre':'Public service-request rows, not distinct customers, unique sites or confirmed high-load facilities.',
 'units':'No SDGE raw kW normalized to MW; no MVA converted to MW; named project equipment, grid capacity and generation capacity distinguished.',
 'latestLimit':'No complete current 2026-10-03 utility census. PG&E imported snapshot June 2025; SDGE December 2025. SCE acquisition incomplete. Later closed/cancelled/energized changes may not be reflected.',
 'badSourceFiles':[{'file':'raw/scepubliceet-september-2025-report20250930ver2.xlsx','issue':'Zero-byte response; not parsed.'},{'file':'raw/sce-september-2025-alternate.xlsx','url':'https://www.cpuc.ca.gov/-/media/cpuc-website/divisions/energy-division/documents/infrastructure/energization/sce-public_attachment-b-energization_report_20250930.xlsx','issue':'Official URL named SCE but actual workbook has SDGE sheets/notes; retained for audit only, excluded from SCE.'}],
 'stageRules':{'PG&E Energized':'Utility service energized by 2025-06-30, not independent proof customer business is operational.','PG&E In-progress':'Submitted in covered period, not energized as of 2025-06-30.','PG&E Cancelled':'Source cancelled/rejected tab; exclude pending.','SDGE Closed':'Finished energization procedure. Narrative Step 8 can be ready-for-service/transformer set or first meter set, so do not label full-site operating.','SDGE Ongoing':'Source ongoing tab as of 2025-12-31; stage cannot be inferred from requested capacity.'},
 'rejectedLeads':[{'name':'PG&E S-238 Hinkley compressor station','source':'https://docs.cpuc.ca.gov/PublishedDocs/SupDoc/A2504004/8832/594293802.pdf','reason':'Source describes natural-gas-engine-driven compressors and replacement auxiliary distribution. No qualifying incremental electric compression load established.'},{'name':'Plug Mendota hydrogen plant','source':'https://www.ir.plugpower.com/press-releases/news-details/2021/Plug-Power-to-Build-Largest-Green-Hydrogen-Production-Facility-on-the-West-Coast-2021-9-20/default.aspx','reason':'Historic 2021 proposal found, current primary development/cancellation status not verified; not imported as pending.'}],
 'files':{'normalized-projects.json':'254 integration-ready anonymous service rows','energization-selected-rows.json':'254 raw selected rows with original headers/cell metadata','energization-inventory.json':'Full-sheet counts, source URLs, SHA256 and headers','energization-excluded-residential-anomalies.json':'225 excluded residential raw >=10000 kW rows for audit','coverage-inventory.json':'14 entries including explicit gaps','named-project-evidence.json':'5 named records, four non-DC, capacity/stage provenance separated','parse_energization.py':'Reproducible XLSX extraction without modifying workbook','build_research_package.py':'Creates evidence inventory/notes/named records'}
})
print('coverage',len(coverage),'named',len(projects))
