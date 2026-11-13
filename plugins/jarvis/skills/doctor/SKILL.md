---
name: doctor
description: Jarvis 가 이상할 때 점검. "/jarvis:doctor", "Jarvis 답이 안 와", "텔레그램이 조용해", "슬랙·디스코드 봇이 답이 없어", "승인 눌렀는데 안 나가", "봇이 죽었어?", "설치 제대로 됐어?", 플러그인 업데이트 뒤 엔진 판 확인. 설정·홈 구조·엔진 판·venv·금고 항목(있는지만)·권한·서비스(맥 launchd · 윈도 작업 스케줄러)·심장박동·실행기 멈춤을 차례로 보고, 고칠 수 있는 것은 고친다.
---

# Jarvis 점검

`P="${CLAUDE_PLUGIN_ROOT}/scripts/install.py"` (비어 있으면, Codex 에서는 늘, 이 SKILL.md 폴더 기준 `../../scripts/install.py`).
`PY` 는 맥 `python3`, 윈도 `py`(없으면 `python`).

## 1. 점검표
`PY "$P" --doctor --json` → `checks` 가운데 ok:false 인 것만 본다. 다 OK 면 "이상 없음" 한 줄과 `jarvis status` 요약.

## 2. 흔한 것과 고치는 법
| 안 맞는 것 | 할 일 |
|---|---|
| 엔진 설정·홈 파일·엔진 코드·venv·jarvis 명령 없음 | 스킬 jarvis:setup 을 그대로(멱등, 있는 파일은 안 덮음) |
| 에이전트 점검(claude·codex 명령, Codex 의 AGENTS.md·.agents/skills·플러그인) | `jarvis agent status` 로 자세히. AGENTS.md·링크는 `jarvis agent sync`, 플러그인은 `codex plugin add jarvis@jarvis-hq`(마켓플레이스가 없으면 먼저 `codex plugin marketplace add minsooparkk/jarvis-hq`) |
| 엔진 판이 플러그인 판과 다름 | 플러그인을 업데이트한 것. setup 을 다시 돌리면 엔진이 새 판으로 바뀌고 데몬이 다시 뜬다 |
| 메신저 토큰 없음 | 사용자가 자기 터미널에서 `~/.jarvis-hq/bin/jarvis secret set telegram`(Slack 은 `slack-bot` 과 `slack-app`, Discord 는 `discord`. 대화에 붙여 넣지 않게) |
| 메신저 설정 확인 | `jarvis messenger status` (모자란 토큰·대표 id 를 알려 줌) |
| 대표 id 없음 | setup 3번의 메신저별 안내(pair → 확인 → set-owner) |
| 권한 설정 다름 | 손으로 고친 흔적이면 고친 내용을 hooks/permissions.json 으로 옮기자고 하고, 아니면 `jarvis perms build` |
| 서비스 등록 안 됨(launchd·작업 스케줄러) | setup 4번(토큰·대표 id 가 있어야 등록된다) |
| bash 없음(윈도) | Git for Windows 를 깔고(https://git-scm.com) setup 을 다시 |
| 심장박동 멈춤 | `~/jarvis/.harness/state/logs/jarvisd.log` 끝 40줄을 읽고 원인 한 줄. 지킴이가 5분 안에 다시 띄운다. 계속이면 setup 4번 |
| 실행기 멈춤 표시 | 사용자가 일부러 멈춘 것인지 묻는다. 풀기는 사용자 터미널에서 `jarvis exec resume`(Jarvis 는 풀지 않음) |

## 3. 승인했는데 안 나갈 때
- `jarvis exec show R-n` 의 상태·메모를 본다. '승인' 이고 메모가 '기다림: …시에만' 이면 창 때문이다. '실행 안 함' 이면 이유(봉인 불일치 등)를 쉬운 말로.
- 실행기 로그: `~/jarvis/.harness/state/logs/executor.log`.

## 4. 알릴 때
결과부터 한두 줄, 사용자가 할 일이 있으면 그것만. 로그 원문은 `⟦작업용⟧` 아래에.
