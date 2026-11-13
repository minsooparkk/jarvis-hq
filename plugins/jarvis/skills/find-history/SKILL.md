---
name: find-history
description: 지난 일을 찾을 때. "어제 뭐 했지", "저번에 만든 거 어디 있지", "배포됐어?", "언제 보냈지", "○○ 정했던 거 뭐였지" 같은 질문에 한 일 기록·실행 장부·결정 기록·작업 폴더에서 위치와 근거를 찾아 답할 때. 읽기만 한다.
---

# 기록 찾기

## 어디를 보나 (이 순서로)
1. 한 일 기록: `jarvis log show --days 7`(또는 `--date 2026-01-31`). 낱말로: `grep -rn "낱말" ~/jarvis/.harness/log/`.
2. 실행 장부(보냄·배포·설정 바꿈): `jarvis exec list` → `jarvis exec show R-n`.
3. 결정: `grep -rn "낱말" ~/jarvis/.harness/decisions/`.
4. 배운 것: `~/jarvis/.harness/memory/`, 그리고 관련 스킬 문서.
5. 결과물 파일: `~/jarvis/.harness/work/` 와 기록의 근거 칸에 적힌 경로. `ls -lt` 로 최근 것.
6. 저장소 이력: `git -C <저장소> log --since=... --oneline`.

## 답 모양
- 결과부터: "1월 30일 15:20 에 했습니다(#요청4, 완료)."
- 근거는 맨 끝 `⟦작업용⟧` 아래에 경로·요청 번호.
- 못 찾으면 어디까지 봤는지 한 줄과 "기록에 없음". 추측으로 채우지 않는다.
- 기록에 빠진 것이 보이면(했는데 기록이 없음) `jarvis log add` 로 채우고 그렇게 했다고 한 줄.
