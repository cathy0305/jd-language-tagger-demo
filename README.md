# JD 우대 언어 자동 분류 봇 (공개용 데모)

> **이 저장소에 대하여**
> 원티드랩 글로벌 파트너팀 인턴(2026.05~07) 기간에 제가 직접 기획·제작해 실제 업무에 사용한 도구를 **공개용으로 재구성한 데모**입니다.
> 사내 시스템 정보, API 키·계정·프로젝트 ID, 실제 채용공고와 기업 데이터, 운영·인수인계 문서는 모두 제거했습니다.
> 저장소에 들어 있는 공고 문구와 분류 규칙은 작동 방식을 보여 주기 위한 **예시**입니다.

## 왜 만들었나

글로벌 채용 서비스에서는 채용공고(JD)마다 "어떤 외국어를 우대하는지"를 태그로 붙여 검색 필터와 기업 소개자료에 씁니다.
기존에는 팀원 6명이 한 번에 약 500개 공고를 나눠 읽으며 각자 약 1시간씩 손으로 분류했습니다.

## 무엇이 바뀌었나

- Slack에서 `/classify <구글 시트 URL>` 한 줄이면 비어 있는 Language 칸을 AI가 채웁니다.
- 애매한 공고(예: "영어권 거주 경험 우대")는 **추측하지 않고 회색 칸으로 남겨** 사람이 확인합니다.
- 팀원 피드백으로 분류 기준을 여러 번 고친 뒤, 봇 실행 후 사람이 확인할 공고는 **약 3~5건**으로 줄었습니다.
- 에러가 난 행만 다시 실행하면 자동으로 재처리됩니다.

## 동작 구조 (운영 버전)

```
Slack /classify ──▶ Apps Script(신호 전달) ──▶ GitHub Actions ──▶ Python
                                                        · 시트 읽기
                                                        · LLM preset API 병렬 호출
◀────────────── 결과 알림 (Slack) ────────────── · 시트에 결과 쓰기 + 회색 표시
```

- 항상 켜 둘 서버 없이 요청이 올 때만 GitHub Actions에서 실행됩니다.
- 분류 규칙(프롬프트)은 코드가 아니라 LLM preset에 두어, 개발 없이도 기준을 고칠 수 있게 했습니다. → 예시: [`prompt_example.md`](prompt_example.md)

## 바로 실행해 보기 (키 없이)

```bash
python demo_local.py
```

`demo/sample_jobs.csv`의 예시 공고 5건을 규칙 기반 목업으로 분류하고 `demo/output.csv`에 저장합니다.

```
   Global Sales Manager         → en, ja
   Backend Engineer             → en
   Customer Support (Tokyo)     → en, ja
–  Marketing Associate          → X
👀 Overseas Sourcing MD         → zh        (사람 확인 필요)
```

## 파일 구성

| 파일 | 역할 |
|---|---|
| `classifier.py` | LLM preset API 병렬 호출 · 응답 파싱 · 구글 시트 일괄 업데이트 (운영 로직) |
| `run_once.py` | GitHub Actions가 실행하는 진입점 |
| `apps_script/classify_shim.gs` | Slack 명령을 받아 GitHub Actions를 깨우는 신호 전달기 |
| `.github/workflows/classify.yml` | 실행 워크플로 |
| `demo_local.py`, `demo/` | 공개용 데모 (키 없이 실행) |
| `prompt_example.md` | 분류 규칙 예시 |

## 결과 값의 의미

| 값 | 의미 |
|---|---|
| `en`, `ja`, `zh`, `etc` | 우대·필수 외국어 (여러 개면 콤마) |
| 회색 빈 칸 | 애매해서 사람이 확인 |
| `X` | 외국어 요구 없음 |
| `HTTP 500`, `TIMEOUT`, `PARSE_ERROR` | 일시적 에러 → 다시 실행하면 해당 행만 재처리 |
