---
name: send-mail
description: 메일을 보내거나 답장할 때, 메일 초안을 만들 때. "○○한테 답장해", "이 메일 보내줘", "초안 만들어", "회신 써 줘" 같은 말. 초안은 메일 MCP(Gmail·Outlook)로 만들고, 보내기는 승인 요청(Gmail 선택 모듈 gmail-send 대상)으로만. 메일 읽기·찾기는 스킬 jarvis:read-mail.
---

# 메일 보내기

메일은 되돌릴 수 없다. 직접 보내지 않는다(메일 MCP 의 보내기·답장·전달 도구는 문지기가 막는다).

## 길 고르기
1. 초안만 필요하면: 메일 MCP 의 초안 도구(Gmail `create_draft`, Outlook `outlook_create_draft`·`outlook_create_reply_draft`).
   사용자가 휴대폰 메일 앱에서 직접 보낼 수 있다고 알린다.
2. Jarvis 가 보내야 하면: Gmail 선택 모듈로 승인 요청(아래). 준비가 안 됐으면 초안까지 만들고 '처음 한 번' 을 안내한 뒤 멈춘다.
3. 메일 MCP 도 없고 선택 모듈도 없으면: 본문을 메신저에 붙여 넣기 좋은 모양으로 주고, 무엇을 연결하면 되는지 한 줄로(claude.ai 의 Gmail 연결 켜기).

## 쓰기
- 이전 대화가 있으면 답장으로 쓴다(새 메일로 보내면 대화가 끊긴다). 원래 메일의 Message-ID(<…@…>)와 Gmail 스레드 ID 를 읽기 때 적어 둔다(스킬 jarvis:read-mail).
- 받는 사람 주소는 읽은 메일·연락처에서 확인한 것만. 이름만 듣고 짐작하지 않는다.
- 본문은 사실만. 받는 사람이 몰라도 되는 내부 사정은 넣지 않는다. 사용자의 말투(rules/00-나에-맞추기)대로.

## 보내기(승인 요청)
- 본문을 .harness/work/mail/ 아래 글 파일로 쓴다.
- `jarvis mail request --to 주소 --subject "제목" --body-file 파일 [--cc 주소] [--reply-to "<원래 Message-ID>" --thread-id 스레드ID] --if-rejected "보내지 않습니다" --결론 "…" --배경 "…"`
  - 제목이 Re: 로 시작하는데 --reply-to·--thread-id 가 없으면 거절된다(새 메일로 나가지 않게).
  - 승인 글에 받는 사람·제목·본문 앞부분이 봉인된 그대로 보인다. 승인되면 실행기가 한 번만 보낸다.
- 상태: `jarvis exec show R-n`. '불확실' 이면 다시 보내지 말고 보낸편지함을 확인해 달라고 한다.

## 처음 한 번 (Gmail 선택 모듈, 사용자가 자기 맥에서)
1. Google Cloud 콘솔에서 프로젝트 → Gmail API 사용 → OAuth 클라이언트(데스크톱 앱) 만들기.
2. 터미널: `jarvis secret set gmail-client-id` 와 `jarvis secret set gmail-client-secret` (값은 대화에 붙여 넣지 않는다).
3. 터미널: `jarvis mail auth` → 브라우저에서 보낼 계정으로 허락.
4. hooks/targets.yaml 의 gmail-send 주석 풀기: Jarvis 가 바꾼 내용을 config-apply 승인 요청으로 낸다(스킬 jarvis:approval-request).
5. `jarvis mail status` 가 모두 '있음' 이면 끝.
Outlook(Microsoft 365) 보내기 모듈은 아직 없다. Outlook 은 초안까지만.
