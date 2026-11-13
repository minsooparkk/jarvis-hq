---
name: infra-ops
description: 이 컴퓨터의 서비스(맥 launchd·윈도 작업 스케줄러)·비밀값 이름·디스크·예약·감시를 보거나 바꿀 때. "서버 죽었어?", "Jarvis 서비스 상태", "감시 켜/꺼", "예약 바꿔", "비밀값 넣어야 해", "디스크 얼마 남았어", "알림이 너무 와" 같은 말. 비서 자신의 서비스(jarvisd·실행기·지킴이) 상태 보기와 일반 서비스 운영 요령.
---

# 인프라 운영

## 철칙
- 비밀값 원문은 읽지도 찍지도 적지도 않는다. 확인은 이름·있는지로만(`jarvis secret list`). 값은 사용자가 자기 터미널에서 `jarvis secret set 이름`.
- 바꾸기 전에 되돌릴 길: 설정 파일은 `.harness/state/backup/날짜/` 에 사본. 바꾼 뒤 확인이 하나라도 실패하면 되돌린다.
- 비서 서비스(이름이 설정의 label_prefix 로 시작)를 내리거나 다시 켜는 것은 문지기가 막는다. 필요하면 스킬 jarvis:setup(다시 돌리기)이나 jarvis:doctor.
- 서비스 다시 켜기는 쓰는 사람이 없을 때만. 남의 운영 서비스를 내리는 일은 승인(되돌릴 수 없는 영향이 있을 때).
- Docker 볼륨은 지우거나 정리하지 않는다.

## 자주 하는 일
**비서 상태**: `jarvis status` (심장박동·승인 대기·멈춤). 서비스: 맥 `launchctl list | grep <label_prefix>` (PID 가 '-' 이고 종료 코드가 0 이 아니면 내려간 것),
윈도 `schtasks /Query /TN <label_prefix>.jarvisd /V /FO LIST`. 로그: `~/jarvis/.harness/state/logs/`.

**예약 켜고 끄기**: `~/jarvis/schedule.yaml` 이나 `skills/<이름>/schedule.yaml` 의 `상태:` 를 고친다(jarvisd 가 매분 다시 읽는다). 무엇을 왜 바꿨는지 한 줄 주석과 기록.

**새 감시 넣기**: 판단이 필요 없으면 스크립트로(스킬 jarvis:make-workflow). 바뀐 것이 있을 때만 글이 나가게, 같은 알림은 `jarvis notify dm "…" --once 열쇠 --hours 6`. 임시 상태 파일로 한 번 돌려 본 뒤 예약에 `종류: 스크립트` 로.

**비밀값이 새로 필요할 때**: ① 이름을 정한다(예: `myservice-api-key`) ② 사용자에게 "터미널에서 `jarvis secret set myservice-api-key` 를 돌려 값을 넣어 주세요" 한 줄 ③ 그 값을 쓰는 프로그램은 엔진의 `jhq.secrets.get("이름")` 으로 읽게 만든다(파일·환경변수에 적지 않는다).

**디스크**: `df -h ~`(윈도 Git Bash 도 됨). 정리는 지우지 않고 `~/.Trash/` 로. 큰 것: `.harness/work/` 의 오래된 작업 폴더(스킬 jarvis:code-work '치우기').

## 요령
- macOS 에는 GNU `timeout` 이 없다: `perl -e 'alarm N; exec @ARGV' …`. 윈도 Git Bash 에는 `timeout` 이 있다.
- 윈도: 셸은 Git Bash 다(`/c/Users/…` 꼴 경로도 된다). 실행 대상·예약 스크립트도 Git Bash 로 돈다.
- cron 은 일(day)과 요일을 둘 다 맞아야 돈다(`30 5 1-7 * 1` = 첫째 월요일).
- 서비스로 뜬 프로그램의 PATH 는 짧다(특히 맥 launchd). 명령은 절대경로로.
