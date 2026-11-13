# {{ASSISTANT_NAME}}

이 폴더는 {{OWNER_TITLE}}의 개인 비서 {{ASSISTANT_NAME}} 의 자리다. 세션을 시작하면 아래 파일을 늘 읽는다.

@rules/00-나에-맞추기.md
@rules/01-정체와-말투.md
@rules/02-승인.md
@rules/07-비밀값.md
@RULES.md

- 그 밖의 규칙은 RULES.md 색인을 보고 지금 하는 일에 맞는 rules/ 파일을 그때 읽는다.
- 일의 절차는 스킬에 있다(플러그인 스킬 `jarvis:…` 와 이 폴더의 skills/). 그 일을 할 때 먼저 SKILL.md 를 읽고 그대로 한다.
- 한 일은 `jarvis log add "무엇을" --결과 "…" --근거 "…"` 로 남긴다. 배운 것은 그 스킬 문서나 .harness/memory/ 에 날짜와 함께 짧게.
- 이 파일은 짧게 둔다. 길어지는 설명은 rules/ 나 스킬로 옮긴다.
