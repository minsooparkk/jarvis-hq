# skills: 이 비서만의 절차

한 절차 = 폴더 하나(`skills/<이름>/SKILL.md`). Claude Code 는 `.claude/skills`(이 폴더로 가는 바로가기)로 읽는다.
플러그인에 든 범용 스킬(`jarvis:…`)과 따로, 이 사람에게 맞춘 절차를 여기에 둔다.

## 새 스킬 만들기
- 스킬 jarvis:make-workflow 가 순서대로 만든다(입력 길 → 스크립트 → 판단 절차 → 예약).
- 모양:
  ```
  skills/<이름>/
    SKILL.md          맨 위에 --- name: 이름 / description: 언제 쓰는지 --- , 아래에 절차
    scripts/          판단이 필요 없는 단계(선택)
    schedule.yaml     예약(선택, 이 폴더의 schedule.yaml 과 같은 모양)
  ```
- 플러그인 스킬을 고쳐 쓰고 싶으면 그 폴더를 여기로 복사해 이름을 바꾼다(docs/고치기.md).
