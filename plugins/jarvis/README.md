# jarvis 플러그인

메신저(텔레그램 · Slack · Discord)로 부리는 개인 비서 Jarvis 의 Claude Code 플러그인. macOS·Windows.

```
/plugin marketplace add minsooparkk/jarvis-hq
/plugin install jarvis@jarvis-hq
```
(Claude Code 2.1.275 이상은 한 번에: `/plugin install jarvis --marketplace minsooparkk/jarvis-hq`)
그다음 `/jarvis:setup`. 점검은 `/jarvis:doctor`, 제거는 `/jarvis:uninstall`.

- skills/: 범용 스킬(승인 요청, 코드 작업, 메일 읽기·보내기, 캘린더, 하루 브리핑, 아침·저녁 요약, 할 일, 받아쓰기, 인프라 운영, 워크플로 만들기, 기록 찾기, 브라우저 보내기 예시)
  와 바깥에서 들여온 스킬 둘(원본 그대로): 제안서·보고서 PPT(`proposal-deck-kr`), 한국 세법 검토(세법 MCP 근거)
- .mcp.json: 세법 검토 스킬이 쓰는 MCP 서버 `korea-tax-law`(공개 주소, 로그인 없음, 읽기 전용). 플러그인을 켜면 함께 붙는다
- hooks/: 문지기(PreToolUse)와 세션 시작 맥락(SessionStart)
- template/: 사용자 홈(~/jarvis) 틀
- engine/: 데몬·실행기·지킴이·jarvis 명령(설치 때 ~/.jarvis-hq 로 복사)
- scripts/install.py: 설치·점검·제거

자세한 설명은 저장소 맨 위 README.md 와 docs/.
