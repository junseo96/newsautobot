# 미국 전력망 관측소

Private dashboard: maps, EIA actual hourly load/fuel mix, generation/load interconnection queues, ordinal remaining-stage scores, policy scenarios and durable weekly/monthly observations.

## Sources and scope

- `data/seed.json` and `data/projects.json`: verified October 2, 2026 workbook. LBNL generation snapshot December 31, 2025; 8,513 source records, 8,509 US-grid scope (unknown locations retained, four known foreign records excluded). Physical projects differ from component records.
- Generation, storage, large-load requests and actual operating load are different quantities. Never subtract nameplate queue GW from requested load GW as firm supply balance.
- Census January 1, 2026 state geometry; ISO polygons are OPTIONAL HIFLD 2020 historical reference. 2026 SPP West territory is not inferred from old polygons or retroactively assigned to the 2025 queue.
- EIA-930 public gridmonitor: hourly MWh / 1 hour / 1000 = time-average GW. Demand and fuel mix have separate timestamps, fuel mix often released later. SPP East and West are separate selectable BA series; US48 is a non-duplicated federal aggregate. Alaska/Hawaii outside EIA-930 US48.
- The 0–100 scores are ordinal procedural proxies, not completion probabilities, calibrated delay measures, or whole-project risk estimates. Unknown stages retain ranges.

## Durable update workflow

This project uses D1 datasets, dated regional snapshots, review logs and schedule settings. Browser polling is not the unattended updater. Routine updates write data without rebuilding.

The full retrievable cloud-run plan is `GET /api/update-plan`. A fresh cloud task must use the linked Site ID with Sites `get_site`, verify owner-private access, and obtain the supported service credential from that response. Send it ONLY to this Site using `OAI-Sites-Authorization: Bearer ...`, privately through stdin rather than code, files, logs or prompts. No connected sources or user-consent impersonation required: data sources are official public endpoints.

1. GET update-plan and current /api/data. Review current source dates.
2. Run `operatingParserPython` from GET update-plan (also scripts/fetch-eia.py) in the cloud task and POST each emitted ingest-live payload to /api/updates. This source-reading route is independent of Worker egress. Optionally refresh-live can fetch directly when available. Verify GET /api/live?mode=stored&ba=... after writes.
3. Check official queue and policy sources specified by update-plan. Parse genuinely new official records, retain source snapshot dates, do not create missing values. Use region/operator scoped action=ingest only when the replacement scope is complete; temporary partial source results must not erase records.
4. Update policy rows and loadEvidence only with verified official changes. Preserve definitions, dates, sources and uncertainty. Check ERCOT aggregate contradictions, Georgia announced vs contracted/ramping distinctions, and BPA line/load scope.
5. POST action=review with every source's updated/unchanged/unavailable status and note. This saves regional dated snapshots. Monthly display selects the last available observation in each month, weekly view shows check-date snapshots. Pre-baseline history is not invented.
6. Read GET /api/data, /api/projects?region=..., /api/history?region=... and reconcile counts/GW. Failed source access keeps previous verified values and their dates. Report unavailable sources explicitly.

The shared writer relies on the platform owner-private boundary and blocks cross-origin browser writes. Do not change this Site to public or add viewers/editors without implementing appropriate narrower writer authorization. No secrets in repository.

## Validation

TypeScript type check; source/workbook totals; successful production build; interactive map, queue drilldown, policy calculation; live official source fetch; actual production service writer plus readback before schedule creation.

## Local commands

Use bundled Sites setup/preview/build and publishing workflow. Generate D1 schema-only migrations via `npm run db:generate`. Applied migration files are immutable. Do not run schema DDL during requests.


## 수용가 자료 공백 보완

`수용가 데이터` 탭은 공개 프로젝트 원장과 유틸리티·규제 공시 관측을 별도 표시한다. `GET /api/load-data`에서 정량·미공개 관측, 공개 표본의 용량/단계 확인 건수 및 변경 이력을 반환한다. `POST /api/updates`의 `load-observations`는 확인한 행만 안정 ID로 upsert하며 나머지 행을 유지한다. 날짜 역행, 가산 허용, 단계별 합계 불일치를 차단한다. 관측과 변경로그는 D1 batch로 함께 저장된다. 상업계약은 접속 G6로 자동 변환되지 않으며 공시값은 기존 유효 부하 합계·점수에 반영되지 않는다.

초기 근거는 2026-10-03 재검증한 43개 관측(정량 40개, MW 미공개 3개), 21개 공식 원문. NYISO는 기존 개별 원장을 유지한다. 원문에 월만 표시되면 월 단위 기준일, 정확 일자 미공개 시 null 사용. 자동 갱신은 기존 주간 일정이 `/api/update-plan`의 collection plan과 신규 writer를 읽어 실행한다.

BPA 기존 458개 원장의 source region `Non-RTO West`는 앱의 `West`로 정규화했다. 단순 권역 키 수정이며 추가 접속·병목 해소가 아니다. Line/Load 혼합 원장의 유효 부하 GW 제외를 유지한다.


2026-10-03 화면 해석 수정: 수용가 선택 시 발전 GW·점수 숨김. 공개 부하 집계를 해당 화면 상단에 직접 연결하고, 미수록 개별 원장은 `0건` 대신 `개별 원장 미확보`로 표시한다. ERCOT NPRR1267의 집계 공개 근거와 2026-06-18 당시 총요청 >438 GW 공시를 추가한다. 공시/추출 시점 및 중앙·유틸리티 범위 차이는 보존한다.
