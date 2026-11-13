---
name: setup
description: Jarvis 를 이 컴퓨터(맥 또는 윈도)에 설치하거나 다시 맞출 때(Claude Code 와 Codex 둘 다). "/jarvis:setup", "$jarvis:setup", "Jarvis 설치", "Codex 로 설치해 줘", "비서 설치해줘", "텔레그램 봇 연결", "슬랙으로 쓰고 싶어", "디스코드 봇 연결", "엔진 업데이트했어(플러그인 업데이트 뒤)" 같은 말. 홈 폴더(기본 ~/jarvis)에 규칙·스킬·기록 구조를 깔고, 엔진을 ~/.jarvis-hq 에 설치하고, 메신저 봇(텔레그램 기본 · Slack · Discord)과 서비스(맥 launchd · 윈도 작업 스케줄러)를 띄우고, 봇에 '안녕' 을 보내 답이 오는지까지 확인한다. 다시 돌려도 안전하다(있는 파일은 덮어쓰지 않음).
---

# Jarvis 설치

설치 스크립트는 `${CLAUDE_PLUGIN_ROOT}/scripts/install.py` 다(아래 `$P`). 변수가 비어 있으면(Codex 는 이 변수가 없다) 이 SKILL.md 가 있는 폴더 기준 `../../scripts/install.py`.
외부 패키지 없이 기본 파이썬으로 돈다. 아래 `PY` 는 맥이면 `python3`, 윈도면 `py`(없으면 `python`)다.
macOS·Windows 가 아니면 "아직 macOS·Windows 만 지원" 이라고 알리고 멈춘다.

## 0. 먼저 볼 것
- 지금 이 스킬을 돌리는 것이 누구인지: Claude Code 면 그대로, **Codex 면 아래 모든 `$P` 설치 명령에 `--agent codex` 를 붙인다**
  (데몬이 Codex 로 세션을 띄운다. 이미 설치돼 있으면 `--agent` 없이 돌려도 설정 그대로).
  Codex 의 샌드박스는 홈 밖(~/.jarvis-hq, 서비스 등록, 금고)에 쓰는 명령에 승인을 물을 수 있다. 물으면 사용자에게 승인을 받거나,
  사용자가 자기 터미널에서 같은 명령을 돌리게 한다.
- 운영체제: `uname -s`(맥 Darwin, 윈도 Git Bash 는 MINGW…).
- 윈도면 이것이 다 있어야 한다. 없으면 무엇을 깔지 한 줄씩 알리고 멈춘다.
  - Git for Windows(Git Bash): Claude Code 의 셸이자 Jarvis 가 실행 대상·예약 스크립트를 돌리는 셸. https://git-scm.com
  - Python 3.9 이상(python.org 설치본, 'py launcher' 켬): `py --version`
  - Claude Code 네이티브 설치(claude.exe). Codex 로 쓸 때는 Codex CLI(`npm install -g @openai/codex`). 윈도 Codex 는 아직 실제 기기에서 확인하지 않았다
- `PY "$P" --doctor --json` 으로 지금 상태를 본다. 이미 다 OK 면 "이미 설치돼 있습니다" 와 점검 결과 한 줄로 끝낸다(엔진 판이 다르면 1번부터 다시: 업데이트).
- `claude --version`(Codex 면 `codex --version`)이 되는지 본다(데몬이 이 명령으로 세션을 띄운다).

## 1. 물어볼 것 (한 번에 묻고, 답이 없으면 기본값)
- 홈 폴더 자리: 기본 `~/jarvis`
- 부를 이름(예: 홍길동)과 호칭(기본 '대표')
- 비서 이름: 기본 Jarvis
- 말투 한 줄: 기본 "존댓말, 짧게, 결과부터"
- 메신저: 기본 텔레그램. Slack 이나 Discord 를 원하면 그것. 한 번에 하나만 쓴다(나중에 바꿀 수 있다).
  - 텔레그램: 가장 간단(봇 하나). 그룹 토픽으로 대화를 나눠 돌릴 수 있다.
  - Slack: 이미 쓰는 워크스페이스에 내 앱을 만든다(관리자 허락이 필요한 워크스페이스도 있다). DM 하나만.
  - Discord: 나만 있는 서버를 하나 만들고 봇을 넣는다. DM 하나만.
- 시간대: 묻지 않고 스크립트가 이 컴퓨터 설정에서 읽는다. 결과에 `timezone_unknown: true` 가 있으면 그때 사는 곳의 시간대를 묻고
  `--timezone Asia/Seoul` 처럼 IANA 이름으로 다시 돌린다(예: 서울 Asia/Seoul, 도쿄 Asia/Tokyo, 뉴욕 America/New_York, 런던 Europe/London).
이미 설치된 상태(업데이트)면 묻지 않는다. 있는 rules/00-나에-맞추기.md 는 덮지 않는다.

## 2. 깔기
`PY "$P" --home ~/jarvis --owner-name "이름" --owner-title "대표" --assistant-name "Jarvis" --tone "…" --messenger telegram --json`
(`--messenger` 는 telegram · slack · discord. 고른 메신저가 Slack·Discord 면 웹소켓 패키지 하나를 엔진 venv 에 더 받는다.)
- 결과 JSON 의 `created`(새로 깐 파일)·`kept`(이미 있어 그대로 둔 파일)·`engine`·`venv`·`timezone`·`warnings`·`next` 를 본다.
- venv 를 만들고 PyYAML(윈도는 시간대 자료 tzdata 도)을 받느라 인터넷이 필요하다. 실패하면 오류 한 줄과 함께 멈추고, 인터넷 연결 뒤 다시 돌리면 된다고 알린다.
- 명령 자리: 맥·윈도 Git Bash 모두 `~/.jarvis-hq/bin/jarvis`. `~/.local/bin` 이 PATH 에 있으면 그냥 `jarvis`.
  윈도의 PowerShell·명령 프롬프트에서는 `jarvis`(= `~\.local\bin\jarvis.cmd`) 또는 `~\.jarvis-hq\bin\jarvis.cmd`.

## 3. 메신저 봇 (사람 손이 필요한 곳)
고른 메신저의 안내를 이 SKILL.md 옆 `messengers/` 폴더에서 읽고 그 순서대로 한 단계씩 같이 한다(한 번에 다 쏟지 말고, 화면에서 무엇을 누를지 한두 줄씩):
- 텔레그램: `messengers/telegram.md`
- Slack: `messengers/slack.md` (앱 매니페스트 `messengers/slack-app-manifest.yaml` 을 붙여 넣기만 하게)
- Discord: `messengers/discord.md`
(자리는 이 SKILL.md 가 있는 폴더 기준. Claude Code 에서는 `${CLAUDE_SKILL_DIR}` 이 그 폴더다.)

공통 원칙
- 토큰은 사용자가 자기 터미널(이 대화 말고)에서 `jarvis secret set …` 으로만 넣는다. 입력은 화면에 보이지 않는다.
  - 맥: '터미널' 앱에서 `~/.jarvis-hq/bin/jarvis secret set …`
  - 윈도: 'PowerShell'(또는 Windows 터미널)에서 `jarvis secret set …`. Git Bash 창은 입력 숨기기가 안 될 수 있어 쓰지 않는다.
  **토큰을 이 대화에 붙여 넣지 말라고 꼭 말한다.** 붙여 넣었으면 쓰지 말고 그 토큰을 새로 받게(재발급) 한다.
- 넣었다고 하면 `jarvis messenger status` 로 모자란 것이 없는지 본다(값은 보이지 않고 있음/없음만).
- 대표 id: `jarvis messenger pair --wait 120` 으로 봇에게 말을 건 사람을 찾고, 나온 이름이 본인이 맞는지 물어 확인받은 뒤
  `jarvis messenger set-owner <id>`. 다른 사람 이름이면 넣지 않는다. (예전 명령 `jarvis telegram pair` 도 된다.)

## 4. 서비스 띄우기
- 2번 명령을 다시 돌린다(같은 인자, 멱등). 이번에는 토큰과 대표 id 가 있어 서비스 셋(jarvisd·실행기·지킴이)을 등록한다.
  결과의 `services`(맥 launchd · 윈도 작업 스케줄러 명령)와 `warnings` 를 본다.
  - 맥: '백그라운드 항목 추가' 알림을 띄우면 허용해 달라고 한다.
  - 윈도: 관리자 권한은 필요 없다. 콘솔 창은 뜨지 않는다. 컴퓨터에 로그인해 있는 동안 돈다.
- `jarvis messenger test` 로 DM 에 시험 글이 가는지 본다.

## 5. 동작 확인
- "메신저에서 봇에게 '안녕' 이라고 보내 주세요" → `jarvis status --wait-reply 180 --json`.
- `replied: true` 면 끝. 아니면 `~/jarvis/.harness/state/logs/jarvisd.log` 끝 30줄을 읽고 원인을 한 줄로(토큰 오류, claude·codex 를 못 찾음, Codex 로그인 안 됨, 맥 허용 창 등) 알리고 고칠 것을 고친 뒤 다시 확인한다.
- Codex 로 설치했으면 `jarvis agent status` 를 돌려 점검이 다 OK 인지 보고, 문지기 표에서 Claude 와 다른 점(약함·꺼 둠)을 사용자에게 두세 줄로 알린다.

## 6. 마치며 알릴 것 (짧게)
- 홈 폴더 자리, 메신저 DM 에서 쓰는 명령(/상태 · /승인 · /new · /stop. Slack 은 `/` 로 시작하는 말을 Slack 이 가로채므로 한 낱말로 '상태'·'승인'·'도움'·'새로'·'멈춰'),
  승인 버튼이 오는 방식(되돌릴 수 없는 일만, 버튼을 눌러야 승인. 글자로 '승인' 이라고 쓰면 승인이 아니라 대기 목록을 다시 보여 줌).
- 다음에 해 볼 것: "내일 할 일 정리해 줘", 메일·캘린더를 쓰려면 claude.ai 의 Gmail·Google Calendar 연결을 켜고
  `~/jarvis/hooks/permissions.json` 의 allow 에 그 도구를 더한 뒤 `jarvis perms build`(Jarvis 가 대신 해 줄 수 있음, 승인 필요).
  Codex 로 돌 때는 ChatGPT 앱(연결)을 데몬 세션에서 꺼 두어 메일·캘린더 스킬을 아직 못 쓴다고 알린다.
- 에이전트 바꾸기: 사용자 터미널에서 `jarvis agent set codex`(또는 `claude`). Jarvis 가 대신 하지 않는다(문지기가 막음).
- 윈도면: '휴지통' 은 윈도 휴지통이 아니라 사용자 폴더의 `.Trash` 폴더다(Jarvis 가 지우는 대신 옮기는 곳).
- 한 일 기록: `jarvis log add "Jarvis 설치" --결과 "…"`.

## 하지 않을 것
- 토큰·비밀값을 이 대화에서 받거나 찍지 않는다. 금고(키체인·자격 증명 관리자)를 직접 읽지 않는다.
- 이미 있는 사용자 파일을 지우거나 덮지 않는다(스크립트가 지킨다). 엔진 옛 판은 ~/.jarvis-hq/backup/ 에 남는다.
- macOS·Windows 가 아닌 곳에는 깔지 않는다.
