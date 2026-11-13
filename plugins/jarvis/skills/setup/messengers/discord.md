# Discord 봇 연결

Discord 봇은 같은 서버에 있는 사람에게만 DM 을 보낼 수 있다. 그래서 나만 있는 서버를 하나 만들고 봇을 넣는다.
개발자 포털 화면 글은 영어일 수 있다. 아래 굵은 글이 누를 단추 이름이다.

## 1. 내 서버 만들기 (이미 있으면 건너뜀)
Discord 앱 왼쪽 **+**(서버 추가) → **직접 만들기** → **나와 친구들을 위한 서버** → 이름(예: 내 비서) → **만들기**.

## 2. 봇 만들기
1. 브라우저에서 https://discord.com/developers/applications → **New Application** → 이름(예: Jarvis) → 동의 → **Create**.
2. 왼쪽 **Bot** → **Reset Token** → **Yes, do it!** → 나온 토큰을 **Copy**.
   자기 터미널에서 `jarvis secret set discord` → 붙여 넣고 Enter. **이 대화에 붙여 넣지 않는다.**
3. 같은 **Bot** 화면에서 **Public Bot** 을 끈다(나 말고 아무도 봇을 서버에 넣지 못하게). 아래 **Privileged Gateway Intents** 셋은
   켜지 않아도 된다(DM 글은 메시지 내용 intent 없이 읽힌다).
4. 왼쪽 **General Information** 의 **Interactions Endpoint URL** 칸은 비워 둔다(채우면 버튼 눌림이 Jarvis 에 오지 않는다).

## 3. 봇을 내 서버에 넣기
1. 왼쪽 **Installation** → **Installation Contexts** 에서 **Guild Install** 이 켜져 있는지 본다.
2. **Install Link** 를 **Discord Provided Link** 로 두고, 아래 **Default Install Settings** 의 Guild Install 에서
   **Scopes** 에 `bot`, **Permissions** 에 `Send Messages` 를 고르고 **Save Changes**.
3. 위 **Install Link** 주소를 복사해 브라우저에서 연다 → 1에서 만든 서버를 고르고 **계속하기** → **승인**.

## 4. 대표 정하기
1. Discord 앱에서 그 서버의 멤버 목록에서 봇을 눌러 **메시지**(DM)를 열고 아무 말이나 보낸다.
2. `jarvis messenger pair --wait 120` → 나온 이름이 본인인지 확인 → `jarvis messenger set-owner <owner_id>`.
   (pair 가 안 되면: Discord 설정 → **고급** → **개발자 모드** 켬 → 내 프로필을 오른쪽 클릭 → **사용자 ID 복사** 한 값을 set-owner 에.)

## 알아 둘 것
- 승인 버튼에 '수정' 을 누르면 그 질문 글에 **답장**(Reply)으로 고칠 점을 적는다.
- 다른 사람이 버튼을 누르면 그 사람에게만 '권한이 없습니다' 가 보이고 아무것도 바뀌지 않는다.
- 토큰이 샜으면: 개발자 포털 **Bot** → **Reset Token** → 새 토큰을 2-2처럼 다시 넣는다.
