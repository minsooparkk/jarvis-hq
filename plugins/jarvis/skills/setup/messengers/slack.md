# Slack 앱 연결 (Socket Mode, 공개 주소 필요 없음)

준비: Slack 워크스페이스 하나(앱을 만들 수 있어야 한다. 회사 워크스페이스는 관리자 허락이 필요할 수 있다).
Slack 화면 글은 영어일 수 있다. 아래 굵은 글이 누를 단추 이름이다.

## 1. 앱 만들기 (붙여 넣기만)
1. 브라우저에서 https://api.slack.com/apps 를 열고 **Create New App** → **From a manifest**.
2. 쓸 워크스페이스를 고르고 **Next**.
3. **YAML** 탭을 고르고, 안에 있는 글을 다 지운 뒤 이 폴더의 `slack-app-manifest.yaml` 내용을 통째로 붙여 넣는다 → **Next** → **Create**.
   (앱 이름을 바꾸고 싶으면 붙여 넣은 글의 `name: Jarvis` 두 곳을 바꾼다.)

## 2. 토큰 두 개
1. 왼쪽 **Basic Information** → 아래 **App-Level Tokens** → **Generate Token and Scopes**.
   이름은 아무거나(예: socket), **Add Scope** 에서 `connections:write` → **Generate**. 나온 `xapp-` 로 시작하는 값을 복사.
   자기 터미널에서 `jarvis secret set slack-app` → 붙여 넣고 Enter.
2. 왼쪽 **Install App**(또는 **OAuth & Permissions**) → **Install to 워크스페이스** → **Allow**.
   나온 **Bot User OAuth Token**(`xoxb-` 로 시작)을 복사 → 자기 터미널에서 `jarvis secret set slack-bot` → 붙여 넣고 Enter.
3. **두 토큰 모두 이 대화에 붙여 넣지 않는다.** `jarvis messenger status` 로 둘 다 있는지 본다.

## 3. 대표 정하기
1. Slack 왼쪽 **Apps**(앱) 아래 방금 만든 앱을 눌러 DM 을 열고 아무 말이나 보낸다
   (앱이 안 보이면 위 검색창에서 앱 이름).
2. `jarvis messenger pair --wait 120` → 나온 이름이 본인인지 확인 → `jarvis messenger set-owner <owner_id>`.
   (pair 가 안 되면: Slack 에서 내 프로필 → 점 세 개 → **멤버 ID 복사** 한 값을 set-owner 에 넣는다.)

## 알아 둘 것
- Slack 은 `/` 로 시작하는 말을 자기 명령으로 가로챈다. '상태'·'승인'·'새로'·'멈춰'·'도움' 을 / 없이 한 낱말로 보낸다.
- 승인 버튼에 '수정' 을 누르면 그 질문 글의 **스레드에 답장**으로 고칠 점을 적는다.
- 토큰이 샜으면: 앱 설정 **OAuth & Permissions** → **Revoke**·다시 설치, **App-Level Tokens** 는 지우고 새로 만든 뒤 다시 넣는다.
