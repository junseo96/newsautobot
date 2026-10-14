import json
from pathlib import Path

BASE = Path(__file__).resolve().parent

def append_unique(filename, record, key):
    path = BASE / filename
    rows = json.loads(path.read_text())
    rows = [row for row in rows if row.get(key) != record[key]]
    rows.append(record)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n')

append_unique('west_additional_contract_records.json', {
    'recordId': 'SDPUC::EL26-008',
    'operator': 'Black Hills Power',
    'region': 'West',
    'state': 'SD',
    'recordType': 'large_load_contract_application_docket',
    'docket': 'EL26-008',
    'customerEntities': ['CSRE Properties South Dakota, LLC'],
    'mw': None,
    'industry': 'crypto_blockchain',
    'sourceUrl': 'https://puc.sd.gov/Dockets/Electric/2026/EL26-008.aspx',
    'sourceTitle': 'SD PUC EL26-008 Blockchain Interruptible Electric Service Agreement',
    'sourceIndexDate': '2026-03-19',
    'sourceDateMeaning': 'Original application filing date; docket checked October 3, 2026.',
    'observedMilestone': 'Contract approval application; amended agreement filed August 19, 2026; public docket explicitly Pending.',
    'regulatoryStatus': 'Pending',
    'currentCustomerInterconnectionStatus': 'unknown',
    'stage': 'GU',
    'include': 0,
    'queueId': None,
    'note': 'Customer name is explicit in public application. Agreement is for a Rapid City facility. MW and material contract terms are redacted in the public amended agreement. Regulatory Pending is not an interconnection gate determination. March application requested approval by June 1; no approval should be inferred from that requested date.',
    'sourceHistory': [
        {'url': 'https://puc.sd.gov/commission/dockets/electric/2026/EL26-008/Application.pdf', 'date': '2026-03-19', 'meaning': 'Application date', 'page': 1},
        {'url': 'https://puc.sd.gov/commission/dockets/electric/2026/EL26-008/Exh1081926.pdf', 'date': '2026-08-19', 'meaning': 'Amended Exhibit 1 filing date', 'page': '1-25'},
    ],
    'confidentiality': 'Docket labels original Exhibit 1 and Amended Exhibit 1 confidential and not available to the public; a redacted amended agreement is public.',
    'checkedAt': '2026-10-03',
}, 'recordId')

append_unique('west_coverage_gaps.json', {
    'operator': 'Black Hills Energy',
    'register': 'April 29, 2026 Annual Meeting presentation slide 13; SD PUC EL26-008',
    'sourceUrl': 'https://ir.blackhillscorp.com/static-files/d80ed8c2-dc95-48c7-90e8-78e174a58353',
    'documentDate': '2026-04-29',
    'publishedRecordDenominator': None,
    'fullHighLoadCustomerDenominator': None,
    'rowsParsed': 1,
    'coverage': 'One additional blockchain contract docket and a dated aggregate pipeline; no full individual queue found.',
    'gap': 'Slide 13 reports a data-center pipeline greater than 3 GW, including large-load requests under non-disclosure agreements and active negotiations. This is not a publicly enumerated customer register or a contracted load total. SD PUC EL26-008 names CSRE Properties South Dakota, LLC, but public agreement versions redact contract quantities. Existing Site Cheyenne 1.8 GW aggregate is not duplicated as individual projects.',
    'confidentialitySource': 'https://puc.sd.gov/Dockets/Electric/2026/EL26-008.aspx',
    'exactProtectedDocument': 'EL26-008 Exhibit 1 – BCIS Agreement Confidential; Amended Exhibit 1 – BCIS Agreement Confidential, filed August 19, 2026.',
    'checkedAt': '2026-10-03',
}, 'operator')

append_unique('west_new_aggregate_observations.json', {
    'id': 'blackhills-2026apr-datacenter-pipeline',
    'region': 'West',
    'operator': 'Black Hills Energy',
    'metricLabel': 'Data-center requests under NDA and active negotiation',
    'valueGW': 3,
    'valueMW': 3000,
    'valueQualifier': 'greater_than_or_plus_as_published',
    'rawValue': '3 GW+',
    'projectCount': None,
    'asOf': '2026-04-29',
    'publicationDate': '2026-04-29',
    'sourceUrl': 'https://ir.blackhillscorp.com/static-files/d80ed8c2-dc95-48c7-90e8-78e174a58353',
    'sourceTitle': 'Black Hills Corporation 2026 Annual Meeting of Shareholders',
    'sourcePage': 'slide 13; PDF page 13',
    'stageClass': 'inquiry_and_negotiation',
    'scope': 'Data-center pipeline includes large-load requests under non-disclosure agreements and active negotiations.',
    'additive': False,
    'includesEnergized': None,
    'remainingGap': 'No complete applicant list, project count, individual MW or current interconnection stages disclosed. Overlaps the separate Cheyenne 1.8 GW negotiation announcement; do not sum.',
    'checkedAt': '2026-10-03',
    'sourceDateMeaning': 'Dated investor presentation; not October 2026 live queue.',
}, 'id')
