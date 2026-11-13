# Codex 로 돌 때 확인할 것 (점검표)

Codex(OpenAI Codex CLI) 지원은 맥에서 codex-cli 0.165.0 으로 만들었다. 아래 '결과' 칸에 **됨** 이라고 적은 것은 실제 codex 로
돌려 본 것이고, 나머지는 문서만 읽었거나 가짜 codex 로만 시험한 것이다(tests/test_agents.py). 새 판이 나오면 차례로 다시 해 보고 칸을 채운다.
안 되는 것이 나오면 고칠 곳(파일)도 적어 두었다.

돌려 본 방법(2026-11-13, macOS, codex-cli 0.165.0, 그때 기본 모델 gpt-6.1-sol)
- HOME 을 임시 폴더로 바꾸고 그 안에 Jarvis 홈·엔진을 깔았다. CODEX_HOME 도 임시 폴더로 바꿔 설치 스크립트와 플러그인 넣기를 했다.
- 임시 CODEX_HOME 은 로그인이 없어 모델을 부를 수 없다(401 이 나는 것까지 확인). 모델을 부르는 시험 넷(짧은 것)은 로그인이 있는
  실제 CODEX_HOME 에 `--ignore-user-config`(사용자 config.toml 을 읽지 않음)를 붙여 돌렸고, 끝난 뒤 그 대화 기록은 `codex delete` 로 지웠다.
  사용자 Codex 설정은 바꾸지 않았다. 그래서 '사용자 설정과 함께 돌 때' 는 확인하지 못했다(4번 표).
- 메신저로 실제 보내기, 서비스(launchd) 등록은 하지 않았다.

## 1. 설치
| # | 해 볼 것 | 기대 | 결과 |
|---|---|---|---|
| 1 | `codex plugin marketplace add <저장소 자리>` → `codex plugin add jarvis@jarvis-hq` | Codex 가 저장소의 `.claude-plugin/marketplace.json` 을 읽어 플러그인을 넣는다. `codex plugin list` 에 `installed, enabled` | 됨(로컬 자리) |
| 2 | 1 다음 `codex debug prompt-input` | 스킬 목록에 `jarvis:setup` 등 플러그인 스킬이 같은 이름으로 보인다 | 됨 |
| 3 | 1 다음 `codex mcp list` | 플러그인 `.mcp.json` 의 `korea-tax-law`(http) 가 등록된다 | 됨 |
| 4 | `codex plugin marketplace add minsooparkk/jarvis-hq`(GitHub) | 1 과 같다 | 못 해 봄(이 판을 아직 올리지 않음) |
| 5 | `python3 plugins/jarvis/scripts/install.py --agent codex …` (dry-run 아님) | config.json 에 agent codex·codex 자리, 홈 AGENTS.md·.agents/skills, 엔진 mcp.json, Codex 에 플러그인 넣기 | 됨(토큰이 없어 서비스는 안 띄움) |
| 6 | 5 다음 `jarvis agent status` | 점검 넷이 OK, 문지기 보장 표가 나온다 | 됨 |
| 7 | 홈에서 `codex debug prompt-input` | AGENTS.md 가 읽히고 홈 skills/ 의 내 스킬도 스킬 목록에 보인다(.agents/skills 링크) | 됨 |
| 8 | Codex 대화에서 '$jarvis:setup' 으로 설치 | 설치 스크립트가 홈 밖(~/.jarvis-hq, LaunchAgents, 키체인)에 써야 해서 Codex 샌드박스가 승인을 물을 수 있다. 물으면 승인하거나 사용자 터미널에서 돌린다 | 못 해 봄 |
| 9 | 그냥 연 Codex 의 `/hooks` | 플러그인의 문지기 훅(hooks/hooks.json)이 '검토 필요' 로 보이고, 신뢰하면 돈다 | 못 해 봄 |

## 2. 대화(jarvisd 가 띄우는 길, jhq/agents/codex.py)
| # | 해 볼 것 | 기대 | 결과 |
|---|---|---|---|
| 1 | `codex exec --json … -` (질문은 표준입력) | 사건: thread.started(thread_id) → item.*(agent_message·command_execution·file_change) → turn.completed | 됨 |
| 2 | 로그인 없음 | turn.failed 401 → 데몬 답 '답을 만들지 못했습니다. 이유: …401…' | 됨(엔진 실행) |
| 3 | `codex exec resume <thread_id> … -` | 앞 대화를 기억한다(같은 thread_id) | 됨 |
| 4 | `-c developer_instructions=…`(메신저 말투) | 모델이 받는 지시에 들어간다 | 됨(prompt-input 에서 봄) |
| 5 | 홈 AGENTS.md | 규칙을 따른다(시험 규칙 문구가 답에 붙음) | 됨 |
| 6 | 샌드박스(workspace-write, 네트워크 꺼짐) 안에서 `jarvis log add`·`jarvis notify dm …` | 홈의 기록·대기열(SQLite)에 써진다 | 됨 |
| 7 | 진행 표시 | 도구 앞의 글은 따로 올라가고(on_text), 도구 이름은 Bash·Edit·mcp__…·WebSearch | 됨(엔진 실행) |
| 8 | 서비스(launchd)로 뜬 jarvisd 가 메신저 말에 답 | PATH 에 codex 자리(npm 의 codex 는 같은 폴더의 node)를 더해 뜬다 | 못 해 봄 |
| 9 | `/stop` | 만들던 답이 멈춘다. npm 의 codex 는 node 래퍼라 SIGTERM 이 진짜 codex 까지 가는지 | 못 해 봄 |
| 10 | 예약(지시) 작업 | 새 대화로 돈다 | 가짜로만 |

## 3. 문지기(가장 중요)
| # | 해 볼 것 | 기대 | 결과 |
|---|---|---|---|
| 1 | 코드 모드(`exec` 자바스크립트 도구) 안의 셸 명령 | PreToolUse 훅이 명령마다 불린다. tool_name `Bash`, tool_input.command 는 글 | 됨 |
| 2 | `jarvis secret set telegram` | 막힌다, Codex 가 명령을 돌리지 않는다 | 됨 |
| 3 | `echo hi > hooks/x.txt` | 막힌다, 파일이 생기지 않는다 | 됨 |
| 4 | apply_patch 로 hooks/gate.json 고치기 | 막힌다(tool_name `apply_patch`, tool_input.command 에 패치 글, 경로는 절대 경로), 파일 그대로 | 됨 |
| 5 | apply_patch 로 홈의 notes/a.txt 만들기 | 통과 | 됨 |
| 6 | 훅을 `-c hooks.PreToolUse=…` 로 주고 `--dangerously-bypass-hook-trust` | 검토(/hooks) 없이 돈다. 시작할 때 경고 사건(item 종류 error) 두 줄이 나온다(데몬은 무시) | 됨 |
| 7 | MCP 도구 이름 | `mcp__<서버>__<도구>` 꼴. 보내기 도구가 막힌다 | 못 해 봄(문서만) |
| 8 | `write_stdin`(이미 띄운 셸에 글 넣기) | 훅이 write_stdin 에도 불려 그 글을 셸 명령처럼 본다 | 못 해 봄. 안 불리면 구멍(Codex 문서도 '다시 보지 않는다' 고 적음). 고칠 곳: 막을 길이 없으면 jhq/agents/codex.py 에서 그 기능을 끈다 |
| 9 | 하위 Agent(spawn_agent)의 명령 | 훅이 불리고, 하위 Agent 표시(agent_id)가 오는지 | 못 해 봄. 지금은 하위 Agent 도 주 Agent 규칙으로 본다 |
| 10 | 네트워크 꺼짐에서 `curl https://…` (`codex sandbox -c sandbox_mode="workspace-write" -- curl …`) | 실패한다(이름 풀기부터 막힘). 켜면 200 | 됨 |
| 10-2 | 같은 샌드박스에서 쓰기 허용 폴더 밖(사용자 폴더)에 파일 쓰기 | Operation not permitted | 됨 |
| 11 | 플러그인의 SessionStart 훅(session_start.py)과 그 additionalContext | 플러그인 훅으로 돌고 모델 맥락에 들어간다(데몬은 이 훅을 따로 걸지 않는다. Claude 와 같음) | SessionStart 훅을 `-c` 로 주면 도는 것(파일을 씀)만 봄. 플러그인 훅으로 도는지·맥락에 닿는지는 못 해 봄 |
| 12 | `features.apps=false` 등 끄기 | ChatGPT 앱(연결) 도구가 사라진다 | 못 해 봄 |
| 13 | 막힌 명령의 사건 | 막힌 명령은 command_execution 사건으로 나오지 않는다 | 됨 |

## 4. 사용자 Codex 설정과 함께 돌 때 (못 해 봄)
| # | 해 볼 것 | 기대 | 결과 |
|---|---|---|---|
| 1 | 사용자 config.toml 의 sandbox_mode·approval_policy·permissions 프로필 | 데몬의 `-c` 가 이긴다(세션 층이 가장 높음) | |
| 2 | 사용자 hooks.json 의 다른 훅 | 데몬 세션에서는 검토 없이 함께 돈다(--dangerously-bypass-hook-trust). 그 훅이 무엇을 하는지 사용자가 안다 | |
| 3 | 사용자 전역 AGENTS.md(~/.codex/AGENTS.md) 가 클 때 | 홈 AGENTS.md 가 잘리지 않는다(project_doc_max_bytes=262144) | |
| 4 | 사용자 MCP 서버 | 도구 승인 방식(default_tools_approval_mode) 이 auto 면 읽기 전용이 아닌 도구는 승인이 필요해 never 정책에서 거절될 것 | |

## 5. 윈도 (전부 못 해 봄)
| # | 해 볼 것 | 기대 | 결과 |
|---|---|---|---|
| 1 | npm 으로 깐 codex(codex.cmd) | node + `node_modules/@openai/codex/bin/codex.js` 를 직접 부른다(cmd 를 거치지 않음) | |
| 2 | 문지기 훅 명령 `"<python.exe>" "<gate.py>"` | Codex 가 윈도에서 훅 명령을 어느 셸로 돌리는지(cmd·PowerShell). PowerShell 이면 `&` 가 필요할 수 있다. 고칠 곳: jhq/agents/codex.py 의 hook_command(commandWindows 쓰기) | |
| 3 | 윈도 샌드박스 | workspace-write 가 윈도에서도 같은 뜻인지 | |
