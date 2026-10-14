import pathlib,json,copy
r=pathlib.Path(__file__).parent
P={x['officialNeedId']:x for x in json.load(open(r/'pjm-transmission-support.json'))}
M={x['transmissionProjectId']:x for x in json.load(open(r/'miso-transmission-support.json'))}
rows=[]
def add(book,id,title,sector,place,review):
 x=copy.deepcopy(book[id]);x.update(displayName=title,sector=sector,location=place,reviewNote=review);rows.append(x)
add(P,'DOM-2025-0080','LS GreenLink USA subsea cable factory','cable manufacturing','Chesapeake, Virginia','Source identifies LS GreenLink; 12 MW requested Q3 2027, ultimate 18 MW in 2033. The 33.6/56 MVA distribution transformer sizes are not customer demand.')
add(P,'DOM-2025-0029','Lewis Drive LNG customer','LNG','Brunswick County, Virginia','ODEC/Mecklenburg Electric Cooperative request explicitly says 25 MW LNG customer; requested service 2026-10-01. No proof of actual energization.')
add(P,'AEP-2023-IM020','New Carlisle manufacturing customer','manufacturing (subsector undisclosed)','New Carlisle, Indiana','Latest register changes 120 MW to 90 MW and requested in-service from December 2025 to May 9 2028. Do not infer company or battery identity from geography.')
add(P,'AEP-2022-AP014','Apple Grove industrial customer / Mercers Bottom','industrial (subsector undisclosed)','Apple Grove, West Virginia','Projected load is 450 MVA, despite 450 entered in a MW-labelled cell. MW stays null. Source does not identify customer; do not silently equate with Nucor.')
add(P,'AEP-2023-AP021','Jackson County industrial customer / Kera Lakes','industrial (subsector undisclosed)','Jackson County, West Virginia','30 MVA initial and 80 MVA maximum; MW stays null. No customer identity disclosed in register.')
add(P,'AEP-2022-AP013','Wythe County glove manufacturing request — withdrawn','glove manufacturing','Wythe County, Virginia','Customer withdrew new delivery-point request 2024-05-17. Historical 59.5 MW must not appear as pending load.')
add(P,'DEOK-2020-002','Fairfield manufacturing request — withdrawn','manufacturing (subsector undisclosed)','Fairfield, Ohio','20 MW request withdrawn 2020-09-11. Source project building activity does not override withdrawal.')
add(P,'DOM-2022-0049','Edgecombe crypto-mining request — withdrawn','crypto','Battleboro, North Carolina','Original load is less than 100 MW. Withdrawal dated 2023-08-08; not pending. Scalar 100 is a bound, not exact MW.')
add(P,'AEP-2019-AP041','Eastman Chemical / Air Products Moreland Drive','chemicals / industrial gas','Sullivan County, Tennessee','Named 47 MW projected peak at new service point. Historical need record persists in 2026 register; current customer energization or pending balance remains unknown.')
add(P,'Dayton-2022-007','Moraine industrial expansion','industrial (subsector undisclosed)','Moraine, Ohio','40 MW added load requested for 2024. Historical requested date does not establish current in-service status.')
add(P,'DEOK-2020-008','Half Acre industrial customer','industrial (subsector undisclosed)','Clermont County, Ohio','New industrial customer requested 36 MW for 2022-10-01. Current delivery status not established.')
add(P,'DLC-2023-002','North Shore / Veterans Bridge construction load','construction','Pittsburgh North Shore, Pennsylvania','20 MW temporary industrial construction load expected for approximately 10 years; requested 2026-01-01. Not a data center.')
add(P,'DEOK-2023-006','Merrel industrial customer expansion','industrial (subsector undisclosed)','Duke Energy Ohio/Kentucky territory; exact location not disclosed','5 MVA requested first quarter 2027, potentially 14 MVA eventually. No MW conversion. Existing substation loads are separate.')
add(P,'DOM-2025-0054','West Creek industrial load request','industrial (subsector undisclosed)','Goochland County, Virginia','Problem statement says 100 MW, raw total cell says >100; MW remains null in normalized conservative dataset because of conflicting qualifier.')
add(M,'51300','Blue Earth data center and ammonia plant','data center + ammonia (combined)','Blue Earth, Minnesota','103 MW combined new load; no defensible split between ammonia and data center. MTEP M1 Proposed as of 2026-07-31, expected transmission ISD 2027-11-30.')
add(M,'51207','Gallagher crypto load interconnection','crypto','Indiana','Approximately 150 MW crypto load. MTEP transmission project M4 In Service as of 2026-07-31; actual customer energization unconfirmed. Never classify as pending interconnection solely from this file.')
add(M,'50198','Wieland Metals / Falls 138 kV connection','metals','Near Wood River, Illinois','MTEP 50198 reports transmission substation under construction, expected 2026-12-01. Customer MW absent; stage stays GU because transmission planning record alone does not define customer stage.')
add(M,'50289','Wabash Industrial new customer','industrial (subsector undisclosed)','Near Chippewa, Indiana','Source reports 20+ MW customer load, so 20 MW is a lower bound; M3 status describes transmission facilities, expected 2026-10-16.')
add(M,'23266','AboutBit Merom load connection','customer load (subsector not stated in source)','Merom, Indiana','115 MVA in project title; customer MW unavailable. MTEP M2 Appendix A approved, expected 2027-01-01.')
add(M,'23964','Kokomo Project Fusion Phase 1','customer load (subsector not stated in source)','Kokomo, Indiana','Grid source identifies Project Fusion but does not identify a battery company or load MW. Transformer capacities must not be substituted for load MW.')
add(M,'25526','Terre Haute Project Tonic Water','customer load (subsector not stated in source)','Terre Haute, Indiana','Source lists load ramp: 33 MW steps on 2025-07-01, 2026-07-01, 2026-11-01 and 31 MW on 2027-03-01; no explicit total requested MW, so normalized mw remains null. MTEP facility is under construction; actual customer draw unknown.')
json.dump(rows,open(r/'industrial-highlights.json','w'),indent=2,ensure_ascii=False)
print(len(rows),'reviewed highlights')
