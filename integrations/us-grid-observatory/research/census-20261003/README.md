# 미국 대형 전력수요 공개자료 조사 · 2026-10-03

공개 원장의 추출·정규화 과정, 출처 목록, 공식 범례와 검토 결과를 보존한 재현성 자료입니다. 데이터센터뿐 아니라 제조업·광업·수소·반도체·배터리 등 모든 업종을 조사하되, 업종이 공개되지 않은 행도 임의로 제외하지 않았습니다. **아래 숫자는 서로 다른 성격의 기록 수이며, 모두 현재 대기 중인 고객 수가 아닙니다. 전국 고객 수나 MW로 합산하지 않습니다.**

## 기록 수와 원장 범위

| 구분 | 반영 기록 수 | 원자료·유형·날짜 | 해석과 한계 |
|---|---:|---|---|
| SPP | 2,449 | [Delivery Point Assessment](https://opsportal.spp.org/Studies/Delivery) 2010~2026년 9월의 199개 월별 워크북. 최신 9월분은 2026-10-01 게시 | 고유 평가 ID 2,447개와 PLP 전용 2개. 원문 2,475행의 중복 게시 이력을 보존. 24개 상세 연구 보고서를 연결했으나, 평가 또는 연구 수행 여부는 현재 고객 접속 단계가 아님 |
| PJM | 1,125 | [TEAC M-3 원장](https://www.pjm.com/committees-and-groups/committees/teac), 2026-10-01 게시·10-06 회의용. 전체 3,057행에서 선택 | Customer Service 1,123행과 추가 용량 기재 2행. 송전 필요·보강 기록이며 고객 대기열이 아님. 고객·지역부하·기존부하 이전·취소 이력 포함 |
| MISO | 161 | [MTEP](https://www.misoenergy.org/planning/transmission-planning/mtep) 평가 원장 2026-07-31, 승인 설비 원장 2026-08-04 | 평가 597행과 승인 설비 3,211행에서 선택한 고유 MTEP 사업 ID. 동일 고객을 지원하는 여러 사업·단계가 포함될 수 있음. 송전설비 준공은 고객 통전 증거가 아님 |
| BPA | 458 | [공식 연결 요청 워크북](https://www.bpa.gov/-/media/Aep/transmission-media-documents/InterconnectionQueueOutput.xlsx)의 모든 LL 행. 생성시각 2026-10-03 03:01:04 | Line/Load 혼합 원장. 철회·통전·송전선·변전소·부하 이전 포함. 여름 서비스 MW 공란 103행. 명시적 선로 전용 7행도 별도 분류하여 보존 |
| NYISO | 74 | [공식 워크북](https://www.nyiso.com/documents/20142/1407078/NYISO-Interconnection-Queue.xlsx)의 Load Projects 모든 유효 Queue Number | 공개 Load Interconnection 전체 행. 원문 기준 활성 53행과 기타 상태 포함. 공식 End-Use·Status 범례로 표시를 보완. 파일 메타데이터 9월 11일과 개별 갱신일 최대 9월 30일을 구분 |
| Georgia Power | 125 | [Q2 2026 PSC 제출자료](https://services.psc.ga.gov/api/v1/External/Public/Get/Document/DownloadFile/227753/109137), 기준일 2026-06-30·제출일 08-17 | 익명 Main 118행 + 보고 범위 이탈 이력 6행 + 별도 기명 OpenAI 1행. 범위 이탈을 모두 취소로 해석하지 않음. 기명 사례가 익명 원장과 중복될 가능성 유지 |
| California | 254 | [CPUC energization 공개자료](https://www.cpuc.ca.gov/industries-and-topics/electrical-energy/infrastructure/energization/energization-data-reporting-requirements-and-data-reporting-template). PG&E 기준일 2025-06-30, SDG&E 2025-12-31 | 총 84,621행 중 tariff 44,901행을 검토해 PG&E 196행·SDG&E 58행 선택. 산업 분류 또는 원문 대형 용량 조건. 254개 확정 대형 고객이 아니며 MW는 모두 미확정. SCE 원장 획득 공백 존재 |
| 서부 계약 관찰 | 10 | NV Energy 5개 docket, Idaho Power 3개, PacifiCorp 1개, Black Hills 1개. 개별 제출·명령 날짜 보존 | 계약 신청·승인·변경 이력 관찰. 한 docket의 여러 법인 또는 기존 계약 변경이 포함되므로 10개 신규 고객으로 해석하지 않음. 확인되지 않은 MW·접속 단계는 공란/미확정 |

ERCOT은 공개 LLI 개별 고객 명부를 확보하지 못했습니다. LLWG·Batch Zero·TSP 자료의 집계와 공개 기명 사례를 보존하며, 계통 전체·유틸리티 부분집합을 더하지 않습니다. ISO-NE의 2026 CELT 대형부하 2행은 전망에 선택된 사업 목록입니다. Maine의 CMP 문의 10건과 Versant 문의 6건은 2026-06-26 공개 의견서의 익명 집계이며, 독립 고객 수·전국 대기열 분모로 사용하지 않습니다.

## 정규화 원칙

- **날짜:** `checkedAt`은 2026-10-03 열람·검토일입니다. 원장 기준일, 게시일, 접수일, 목표 통전일, 개별 행 갱신일을 분리합니다. SPP·BPA 등 기존 `asof:2026-10-02` 수집 표시는 유지하고 `sourceDateMeaning`으로 설명합니다. 10월 6일 회의 자료는 10월 3일 이전 공개가 확인된 자료만 사용합니다.
- **식별자:** SPP의 동일 평가 ID는 한 행으로 정리하고 월별 출처 이력을 남깁니다. PJM Need Number와 MISO MTEP ID는 송전계획 식별자이며 고객 queue ID가 아닙니다. 익명 Georgia 행은 MW만으로 분기 간 또는 기명 고객과 매칭하지 않습니다.
- **용량:** 원문 MW, MVA, 설비 정격, 연구 모델 부하, 고객 발표 최종부하, 계약량을 구분합니다. MVA를 MW로 바꾸지 않으며, 근사·상한·하한·범위 표기를 감사 패치에 남깁니다. 누락 값은 0으로 채우지 않습니다.
- **상태:** 공장 건설·생산 시작·송전설비 준공·study required 결과에서 고객 접속 단계를 추론하지 않습니다. SPP 평가와 PJM/MISO 지원 기록은 `GU`, `include:0`; BPA LL 혼합 기록도 합산 제외입니다. 실제 공개 상태와 분석용 분류를 함께 보존합니다.
- **완전성:** “공개 원장 전체 추출”은 해당 파일·기간·선택 조건의 완전성을 뜻합니다. 지역 전체의 비공개·배전 접수·초기 문의·소규모 산업 고객까지 조사했다는 의미가 아닙니다. 알려지지 않은 전체 분모는 null로 유지합니다.

## 보존 파일과 재현 방법

| 폴더 | 핵심 보존 자료 |
|---|---|
| `california/` | energization 파서, 워크북/시트 inventory, 선택 기준, 단위·자료 획득 오류 기록 |
| `ercot/` | 조사 생성 스크립트, 공식 출처 목록, 집계 증거와 공개 범위 공백 |
| `northeast/` | NYISO 정규화·공식 범례·비교 요약, 용량 감사 패치, ISO-NE 및 Maine 공개 집계 |
| `pjm-miso/` | 다운로드·추출·정규화 스크립트, 전체 원장 분모와 선택식, 공식 파일 manifest와 TEAC 링크 inventory |
| `southeast/` | Georgia 파서·원장 요약, 53개 변경 이벤트, 범위 이탈 6행, TVA 승인 이벤트, 공식 출처 inventory |
| `spp-west/` | SPP 전체 월별 archive manifest·파서·정규화, 상세 연구 근거, BPA 요약, 서부 계약 관찰과 공개 공백 |

`archive-manifest.json`은 이 폴더에 복사한 파일의 바이트 수와 SHA-256을 기록합니다. 지역별 source/download manifest에는 공개 URL, 수집 당시 파일명과 가능한 경우 원본 해시가 있습니다. 파일 안의 연구 경로는 원래 수집 환경의 provenance이며 현재 저장 위치를 가리키는 링크가 아닐 수 있습니다. 지역별 기존 README는 당시 조사 기록으로 그대로 보존했습니다.

재실행 시 별도 작업 디렉터리에 해당 지역 폴더를 복사하고, source manifest의 URL에서 원본을 내려받아 파서가 기대하는 파일명·경로로 배치합니다. Python 3와 해당 스크립트가 사용하는 `openpyxl`, `xlrd`, `lxml` 등이 필요하며 일부 PDF 추출은 `pdftotext`를 사용했습니다. 다운로드 → 원장 추출 → 정규화 → 요약/감사 순서로 실행하고 원본 해시·행 수·고유 ID 수를 비교합니다. 일부 스크립트는 기존 Site의 `data/projects.json`을 비교 기준으로 읽으므로 경로와 기준 버전을 명시해야 합니다. 현재 온라인 원장이 바뀌면 과거 스냅샷과 동일한 결과를 보장하지 않습니다.

이 보존본에는 원본 PDF/XLSX 등 바이너리, 대용량 중복 정규화 행, `before*.json`, 브라우저·검색 payload를 포함하지 않았습니다. 원문 재다운로드와 비교 기준의 별도 확보가 필요한 **경량 재현성 기록**입니다. Georgia 53개 변경 이벤트는 Main 추가 행과 중복될 수 있으므로 독립 고객으로 더하지 않습니다. Maine 집계도 원자료의 지역·업종 범위를 유지합니다.
