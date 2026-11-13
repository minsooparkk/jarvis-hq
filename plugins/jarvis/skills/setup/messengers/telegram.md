# 텔레그램 봇 연결

1. 휴대폰이나 컴퓨터의 텔레그램에서 `@BotFather` 를 찾아 대화를 연다.
2. `/newbot` 을 보낸다. 봇 이름(아무거나, 예: 내 비서)과 아이디(영어, 끝이 bot, 예: my_jarvis_bot)를 차례로 정한다.
3. BotFather 가 준 긴 토큰(숫자:글자 꼴)을 복사한다. **이 대화에 붙여 넣지 않는다.**
4. 자기 터미널에서 `jarvis secret set telegram` → 토큰을 붙여 넣고 Enter(화면에 안 보임).
   (맥은 '터미널' 앱에서 `~/.jarvis-hq/bin/jarvis secret set telegram`, 윈도는 PowerShell 에서 `jarvis secret set telegram`)
5. 방금 만든 봇과의 대화를 열어 `/start` 를 보낸다.
6. `jarvis messenger pair --wait 120` → 나온 이름이 본인인지 확인 → `jarvis messenger set-owner <owner_id>`.

토큰이 샜으면: BotFather 에서 `/revoke` → 새 토큰을 4번처럼 다시 넣는다.
그룹 토픽으로 대화를 나누고 싶으면 docs/고치기.md 의 '텔레그램 그룹'.
