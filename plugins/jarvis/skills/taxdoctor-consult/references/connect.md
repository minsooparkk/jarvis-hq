# TaxDoctor MCP 연결 안내

TaxDoctor MCP 도구가 보이지 않거나 호출이 실패할 때 읽는다. 사용자에게 아래 중 그 사람의 환경에 맞는
한 가지를 안내하고, 연결 뒤 같은 질문을 다시 보내 달라고 한다. 연결 전에는 세법 답을 쓰지 않는다.

- 주소: `https://mcp.taxdoctorai.com/mcp` (Streamable HTTP). 구형 SSE 전용 클라이언트는 `https://mcp.taxdoctorai.com/sse`.
- 로그인·API 키가 필요 없다. 읽기 전용이다.
- 공개 도움말: https://taxdoctorai.com/mcp-guide

## 클라이언트별

- **Claude (웹·데스크톱)**: 설정 → 커넥터(Connectors) → 사용자 지정 커넥터 추가 → URL 에 위 주소.
  대화 창의 도구 메뉴에서 그 커넥터가 켜져 있는지도 확인한다.
- **Claude Code**: 이 스킬을 플러그인으로 설치했으면 MCP 가 함께 붙는다. 따로 붙이려면
  `claude mcp add --transport http korea-tax-law https://mcp.taxdoctorai.com/mcp`
- **Codex CLI** (`~/.codex/config.toml`):
  ```toml
  [mcp_servers.korea-tax-law]
  url = "https://mcp.taxdoctorai.com/mcp"
  ```
- **Gemini CLI** (`~/.gemini/settings.json`): `{"mcpServers": {"korea-tax-law": {"httpUrl": "https://mcp.taxdoctorai.com/mcp"}}}`
- **stdio 만 되는 클라이언트**: `npx -y mcp-remote https://mcp.taxdoctorai.com/mcp` 로 이어 붙인다.

## 호출이 실패할 때

- 한도: IP 당 분당 도구 호출 60회, 연결 인사(initialize·도구 목록) 분당 20회. 한도에 걸리면 응답이 안내하는
  시간만큼 기다렸다가 다시 부른다. 걸린 뒤에도 계속 부르면 잠시 모든 호출이 막힌다.
- 조회 시간 초과(약 8초)·일시 오류는 한 번만 다시 시도한다. 그래도 실패하면 실패를 알리고 멈춘다.
- 서버가 주는 안내 문구(응답 끝의 고지·notice)는 지운 채 결론만 옮기지 않는다.
