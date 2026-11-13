---
name: uninstall
description: Jarvis 를 이 컴퓨터에서 내릴 때. "/jarvis:uninstall", "Jarvis 지워줘", "비서 끄고 제거", "데몬 내려줘" 같은 말. 서비스(맥 launchd · 윈도 작업 스케줄러)를 내리고 엔진과 명령을 휴지통으로 옮긴다. 홈 폴더(규칙·기록)는 기본으로 남긴다. 금고 비밀값과 홈 폴더 제거는 따로 확인받는다.
---

# Jarvis 제거

`P="${CLAUDE_PLUGIN_ROOT}/scripts/install.py"` (비어 있으면 이 SKILL.md 폴더 기준 `../../scripts/install.py`).
`PY` 는 맥 `python3`, 윈도 `py`(없으면 `python`).

## 순서
1. 무엇이 사라지는지 먼저 보여 준다: `PY "$P" --uninstall --dry-run --json`
   - 내리는 서비스(jarvisd·실행기·지킴이), 휴지통으로 가는 것(엔진 ~/.jarvis-hq, 맥 launchd 설정 파일, ~/.local/bin 의 jarvis 바로가기).
   - 휴지통: 맥은 휴지통, 윈도는 사용자 폴더의 `.Trash` 폴더(윈도 휴지통이 아님)라고 알린다.
2. 사용자에게 세 가지를 확인받는다(답이 없으면 '아니오'):
   - 정말 내릴지
   - 홈 폴더(~/jarvis: 규칙·스킬·한 일 기록)도 휴지통으로 보낼지 → 예면 `--remove-home`
   - 금고(맥 키체인·윈도 자격 증명 관리자)의 메신저 토큰·서명 열쇠 등도 지울지 → 예면 `--forget-secrets` (되돌릴 수 없다. 봇 토큰은 BotFather·Slack 앱 설정·Discord 개발자 포털에서 다시 받을 수 있다)
3. 실행: `PY "$P" --uninstall [--remove-home] [--forget-secrets] --json`
4. 결과의 `trashed` 를 짧게 알린다. 휴지통은 사용자가 비운다(Jarvis 는 비우지 않는다).
5. 플러그인 자체를 빼려면 사용자가 `/plugin` 화면에서 jarvis 를 끄거나 제거한다고 안내한다.

## 하지 않을 것
- rm 으로 지우지 않는다(스크립트가 휴지통으로 옮긴다).
- 확인 없이 홈 폴더·비밀값을 지우지 않는다.
- 실행 중인 승인 요청이 있으면(`jarvis exec pending` 에 '실행 중') 끝날 때까지 기다리자고 먼저 말한다.
