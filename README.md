# Jarvis (jarvis-hq)

메신저(텔레그램 · Slack · Discord)로 부리는 개인 비서입니다. 이 컴퓨터(맥·윈도)에서 Claude Code 세션을 대신 띄워 답하고, 정해 둔 시각에 일을 돌리고,
보내기·배포처럼 되돌릴 수 없는 일은 메신저의 승인 버튼을 누른 그대로만 한 번 실행합니다.
메신저는 설치 때 하나를 고릅니다(기본 텔레그램). Slack·Discord 는 아직 실제로 붙여 보지 않았습니다: [docs/메신저-확인할-것.md](docs/메신저-확인할-것.md)

- Claude Code 플러그인 `jarvis` 하나로 설치합니다(이 저장소가 마켓플레이스 `jarvis-hq`).
- macOS 와 Windows 에서 돕니다(맥: launchd·키체인, 윈도: 작업 스케줄러·자격 증명 관리자). Linux 는 아직 지원하지 않습니다.
  윈도 지원은 아직 실제 기기에서 확인하지 않았습니다: [docs/윈도우-확인할-것.md](docs/윈도우-확인할-것.md)
- 공개 저장소, MIT 라이선스([LICENSE](LICENSE)).

## 가장 쉬운 설치: Claude 에게 링크를 주고 시키기
Claude Code 를 열고 아래 한 줄을 그대로 보냅니다.

```
https://github.com/minsooparkk/jarvis-hq 이거 설치해 줘
```

사람이 직접 해야 하는 일은 두 가지뿐입니다: 메신저에서 봇을 만드는 것, 봇 토큰을 터미널에 넣는 것(Claude 가 차례에 맞춰 안내합니다).

### Claude 가 따를 순서 (이 링크로 설치를 부탁받은 Claude 는 이대로 한다)
1. `git --version` 으로 git 이 있는지 본다(윈도는 Git for Windows). GitHub 로그인은 필요 없다.
2. 터미널 명령으로 플러그인을 넣는다: `claude plugin marketplace add minsooparkk/jarvis-hq` 다음에 `claude plugin install jarvis@jarvis-hq`.
3. 지금 대화에는 새 스킬이 아직 안 보일 수 있다. 사용자에게 `/reload-plugins` 를 치거나 Claude Code 를 다시 열어 `/jarvis:setup` 을 불러 달라고 한다.
   다시 열기 어렵다면 설치된 플러그인 폴더의 `skills/setup/SKILL.md` 를 읽고 그 순서대로 진행해도 된다.
4. 봇 토큰은 대화창으로 받지 않는다. 사용자가 자기 터미널에서 `jarvis secret set …` 으로 넣게 한다.
5. 봇에게 '안녕' 을 보내 답이 오는 것까지 확인하고 끝낸다.

## 설치 (손으로 할 때, 3단계)
1. git 이 깔려 있어야 합니다(윈도는 Git for Windows). GitHub 로그인은 필요 없습니다.
2. Claude Code 에서:
   ```
   /plugin marketplace add minsooparkk/jarvis-hq
   /plugin install jarvis@jarvis-hq
   ```
   (Claude Code 2.1.275 이상은 한 번에: `/plugin install jarvis --marketplace minsooparkk/jarvis-hq`)
3. `/jarvis:setup` 을 부르고 안내를 따릅니다. 메신저(텔레그램·Slack·Discord)를 고르고 봇을 만듭니다.
   봇 토큰은 대화창이 아니라 터미널에서 `jarvis secret set …` 으로 넣습니다(화면에 안 보임).
   마지막에 봇에게 '안녕' 을 보내 답이 오면 끝입니다.

필요한 것: Claude Code(로그인된 상태), 메신저 계정 하나(텔레그램 · Slack 워크스페이스 · Discord), 인터넷(설치 때 PyYAML 을, Slack·Discord 면 websocket-client 도 받음). 그리고
- 맥: 기본 python3
- 윈도: Git for Windows(Git Bash), python.org 의 Python 3.9 이상('py launcher' 켬), Claude Code 네이티브 설치(claude.exe).
  토큰은 PowerShell 창에서 넣습니다(Git Bash 창은 입력 숨기기가 안 될 수 있음).

## 처음 해 볼 것
- 봇에게: "오늘 할 일 정리해 줘", "내일 9시에 ○○ 할 일로 넣어 줘", "/상태"
- Slack 에서는 `/상태` 대신 '상태'·'승인'·'새로'·'멈춰' 를 한 낱말로 보냅니다(Slack 이 / 를 가로챔).
- 승인 흐름 시험: "실행기 시험(hello) 승인 요청 올려 줘" → DM 에 버튼이 오면 '승인' → 끝났다는 알림
- 메일·캘린더: claude.ai 연결(Gmail·Google Calendar)을 켠 뒤 "어제 온 메일 중 답할 것", "목요일 오후 비어?"
- 녹음 받아쓰기(선택): `brew install ffmpeg whisper-cpp` 와 모델 파일 하나 → "이 녹음 받아써"
- 제안서·보고서 PPT(스킬 `proposal-deck-kr`): "우리 법인 서비스 소개서 PPT 만들어줘". python-pptx(또는 uv)가 있어야 합니다.
- 한국 세법 검토: "이 양도 건 비과세 맞아?". 플러그인에 실린 세법 MCP 서버(`korea-tax-law`, 로그인 없음)의 법령·판례 원문을 근거로 답합니다.

## 구조
```
~/jarvis/                     사용자 홈(내 것, 고쳐 쓰는 곳)
├─ CLAUDE.md                  진입점: 늘 읽을 규칙 지정
├─ RULES.md                   상황별 규칙 색인
├─ rules/00-…md ~ 13-…md      규칙(00 은 나에게 맞추기, 11~13 은 한국어 글쓰기)
├─ docs/                      규칙이 가리키는 참고 자료(한국어 글쓰기 규칙의 출처 목록)
├─ skills/                    나만의 스킬(.claude/skills 가 여기를 가리킴)
├─ hooks/                     문지기 설정·실행 대상·권한(직접 고치거나 승인으로 바꿈)
├─ schedule.yaml              예약
└─ .harness/                  한 일 기록·결정·memory·장부·상태·작업

~/.jarvis-hq/                 엔진(설치 스킬이 깔고 갱신)
├─ engine/                    jarvisd·실행기·지킴이·jarvis 명령(파이썬)
├─ venv/                      엔진 파이썬
├─ bin/jarvis                 명령(~/.local/bin/jarvis 가 가리킴. 윈도는 jarvis.cmd 도)
└─ config.json                설정(비밀값 없음)

금고                           메신저 봇 토큰·승인 서명 열쇠(맥 키체인 · 윈도 자격 증명 관리자, 값은 아무 데도 적지 않음)
서비스                         com.jarvis-hq.jarvisd · executor · watchdog(맥 launchd · 윈도 작업 스케줄러)
```
자세한 것: [docs/구조.md](docs/구조.md) · [docs/승인과-실행기.md](docs/승인과-실행기.md) · [docs/보안-모델.md](docs/보안-모델.md) · [docs/고치기.md](docs/고치기.md)

## 업데이트·제거
- 업데이트: `/plugin` 에서 jarvis-hq 마켓플레이스를 갱신하고 플러그인을 업데이트한 뒤 `/jarvis:setup` 을 한 번 더(엔진만 새 판으로 바뀌고 홈 파일은 그대로).
  플러그인 판(version)을 고정하지 않아 저장소의 새 커밋이 곧 새 판입니다.
- 제거: `/jarvis:uninstall`. 서비스를 내리고 엔진을 휴지통(윈도는 사용자 폴더의 .Trash 폴더)으로 옮깁니다. 홈 폴더와 금고의 값은 물어본 뒤에만 지웁니다.

## 문제 해결
- 무엇이든 먼저 `/jarvis:doctor`. 점검표와 고칠 방법이 나옵니다.
- 답이 안 옴: 로그 `~/jarvis/.harness/state/logs/jarvisd.log`. 지킴이가 5분마다 멈춘 데몬을 다시 띄우고 DM 으로 알립니다.
- 승인했는데 안 나감: 봇에게 "#요청3 어떻게 됐어?" 또는 터미널에서 `jarvis exec show 3`.
- 실행기를 급히 멈추기: `jarvis exec pause`(다시 켜기는 터미널에서 `jarvis exec resume`).

## 개발
- 시험: `python3 -m pytest`(PyYAML·pytest 필요). 설치 시험은 임시 HOME 에서 돌고 launchd·키체인을 건드리지 않습니다.
  윈도 쪽은 가짜 실행기·가짜 금고로 만드는 명령·파일만 봅니다(tests/test_platform.py).
- 개인정보 검사: `python3 scripts/check_clean.py` (걸리면 끝 코드 1). 올리기 전에 꼭 돌립니다.
- 플러그인 검사: `claude plugin validate plugins/jarvis` · `claude plugin validate .`
- 로컬 시험 설치: `claude --plugin-dir ./plugins/jarvis`
