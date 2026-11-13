# .harness: 기록 폴더

{{ASSISTANT_NAME}} 와 엔진이 남기는 것. 사람이 읽는 기록과 프로그램 장부를 나눠 둔다.

| 폴더 | 무엇 | 누가 쓰나 |
|---|---|---|
| log/ | 한 일 기록(날짜별 YYYY-MM-DD.md, 더하기만) | `jarvis log add`, 실행기, jarvisd |
| decisions/ | {{OWNER_TITLE}}이(가) 정한 것(날짜와 원문) | {{ASSISTANT_NAME}} |
| memory/ | 배운 것·실수와 보완 | {{ASSISTANT_NAME}} |
| ledger/ | 장부: 실행 요청(executor.db)·보낼 글(outbox.db)·봉인한 입력 사본 | 프로그램만(문지기가 직접 쓰기를 막음) |
| state/ | 데몬 상태·심장박동·로그(state/logs/)·설정 사본(state/backup/) | 프로그램 |
| work/ | 작업 폴더(코드 작업 worktree, 받아쓰기 결과 등) | {{ASSISTANT_NAME}} |
| inbox/ | 메신저(텔레그램·Slack·Discord)로 받은 사진·파일(날짜별) | jarvisd |
| todo.md | 할 일 목록(스킬 jarvis:todo) | {{ASSISTANT_NAME}} |

지우지 말고 오래된 것은 휴지통으로 옮긴다.
