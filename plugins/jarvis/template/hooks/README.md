# hooks: 넘으면 안 되는 선

이 폴더의 파일은 {{ASSISTANT_NAME}} 가 직접 고치지 못한다(문지기가 막는다). {{OWNER_TITLE}}이(가) 편집기로 고치거나,
{{ASSISTANT_NAME}} 가 새 내용을 만들어 승인 요청(대상 `config-apply`)을 올리면 승인 뒤 실행기가 바꾼다(옛 파일은 .harness/state/backup/).

| 파일 | 무엇 |
|---|---|
| gate.json | 문지기(Bash·파일·MCP 도구를 쓰기 직전에 보는 훅) 설정. 지워도 되는 폴더, push 해도 되는 원격, 보호할 서비스·DB, '길 고정' 규칙 |
| targets.yaml | 실행기가 승인 뒤 실행할 수 있는 대상. 여기 없는 것은 실행하지 않는다 |
| permissions.json | Claude Code 권한(허용·거부)에 더할 것. 바꾸면 `jarvis perms build` 가 .claude/settings.json 을 다시 만든다 |

문지기 코드는 플러그인(hooks/gate.py)과 엔진 사본에 있다. 이 폴더에는 설정만 둔다.
