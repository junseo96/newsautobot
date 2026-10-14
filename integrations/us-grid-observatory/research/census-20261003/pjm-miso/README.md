# PJM / MISO public load-support census extraction

Checked 2026-10-03. These files are research artifacts outside the Site checkout. No Site files were edited.

## Ready for ingestion

- `pjm-transmission-support.json`: 1,125 rows selected from the complete 3,057-row PJM M-3 register posted October 1, 2026. Includes all 1,123 Customer Service driver rows plus two additional non-null expected-load rows. 418 rows have an explicit MW amount matching the raw expected-load cell; 161 have matching MVA instead and keep `mw: null`. 25 rows flag withdrawal/cancellation of the need or support solution. Covers 21 submitting TOs.
- `miso-transmission-support.json`: 161 distinct MTEP project IDs selected from the complete 597-row July 31 evaluation file and 3,211-facility August 4 approved file. Approved file has 1,497 distinct project IDs. Includes all 111 evaluation records classified Load Growth, plus explicit new-load/customer/interconnection candidates; excludes GIP. 42 explicitly reviewed load-MW entries, including phased/overlapping projects. Covers 30 submitting TOs.
- `industrial-highlights.json`: 21 reviewed industrial or mixed-sector examples and caveats. Includes cable manufacturing, LNG, chemicals, manufacturing, metals, construction, ammonia, crypto and anonymous industrial customers; three expressly withdrawn examples retained as history.
- `coverage-summary.json`: exact source universes, predicates, owner counts and limitations.
- `primary-source-manifest.json`: original sources, dates, local paths and SHA-256 digests.

Every normalized row has `kind: load`, `recordType: transmission_support`, `stage: GU`, `low: 0`, `high: 100`, `include: 0`, `additive: false`, and an empty `queueId`. Official Need Numbers and MTEP/PJM transmission IDs are separately preserved. These are NOT customer queue IDs and NOT pending-load totals.

PJM M-3 records are transmission needs from 2018 onward, with existing-load reliability work, area/distribution forecasts, transferred load, anonymous customers, cancellations and customer service requests. `Total Expected Load (MW)` contains MVA amounts, zeroes and text as well as real MW. The source Notes sheet calls it maximum customer-service load; the underlying Problem Statement must establish units. The broad selection is deliberate to avoid suppressing industries or unknown-MW customers, but its 1,125 rows are not 1,125 unique high-load customers.

Two internal sanitized-ID collisions are preserved with `_ROW_<Excel row>` suffixes and a collision flag. In particular official Need Number DOM-2024-0052 occurs twice for distinct Oslo and Nebula descriptions. Do not merge them silently or interpret an internal suffix as an official identifier.

MISO project and facility status applies to TRANSMISSION ASSETS. M3 Under Construction does not prove customer grid G7; M4 Project in Service does not prove customer energization/G8. MISO multiple projects, phases, temporary taps and upstream upgrades can support the same load; no MW sum is defensible from these records. The Gallagher crypto record is explicitly flagged transmission-in-service/customer-unconfirmed. Cannoli and several NIPSCO/Benton records may overlap existing named-load rows and are not additive.

MW values remain null where there is only MVA or conflicting/unsupported units. `capacityQualifier` retains important bounds when detected, and full source facts remain in `sourceFields`. PJM state/county are intentionally null absent individual geocoding; project descriptions retain original locations. Customer names, sector and current status remain unknown for many rows.

## Primary URLs

PJM M-3 (published 2026-10-01 for 2026-10-06 meeting):
https://www.pjm.com/-/media/DotCom/committees-groups/committees/teac/2026/20261006/20261006-informational-only---m-3-process-needs-status.xlsx

PJM index proving pre-cutoff publication:
https://www.pjm.com/committees-and-groups/committees/teac

MISO evaluation (header 2026-07-31):
https://cdn.misoenergy.org/MTEP%20Projects%20Under%20Evaluation368757.xlsx

MISO approved facilities (header 2026-08-04):
https://cdn.misoenergy.org/Appendix%20A%20Status%20Report575959.xlsx?v=20260514162226

MISO source index / register definitions:
https://www.misoenergy.org/planning/transmission-planning/mtep

## Reproduction

`fetch_sources.py` retrieves linked 2026 PJM supplemental/local-plan PDFs and all three public XLSX registers. `extract_registers.py` reads the first, visible workbook sheets into exact JSON. `normalize_census.py` applies deterministic predicates, preserves all source fields, groups MISO facilities by MTEP ID, and applies a reviewed explicit-MW map for MISO. `build_highlights.py` selects the 21 annotated examples. Raw PDFs, pdftotext extracts, XLSX and PJM HTML are under `raw/`.

Validation completed: row references match original Excel rows; normalized IDs are unique; all support rows are GU/include=0/empty queueId; no MVA conversion was performed. All files are separate from the Site checkout.
