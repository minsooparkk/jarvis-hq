# proposal-deck-kr

회계·세무·컨설팅 법인이 한국어 PowerPoint **제안서·서비스 소개서·자문 보고서**를 같은 기준으로 만들고 고치는 에이전트 스킬입니다([Agent Skills](https://agentskills.io) 형식). Claude Code·Codex 등 스킬을 읽는 에이전트에서 씁니다.

- 블루·Pretendard 원형 두 벌: 제안서 25장(`assets/proposal-template.pptx`), 보고서 9장(`assets/report-template.pptx`). 글·수치·그림은 자리표시입니다.
- 작성 기준: 제목·목차·줄바꿈·표 정렬·단위 표기·보고서 흐름·문체, 리뷰를 모았다가 한 번에 반영하는 방식, 독립성 문구 확인 절차.
- 검사 스크립트: 쪽 번호·진행 번호·목차·글꼴·단위 표기·PowerPoint 호환 구조(`check_deck.py`), 근사 미리보기와 글자 넘침(`render_preview.py`), 실제 PowerPoint 열기·PDF 렌더·한글 단어 중간 끊김(`powerpoint_check.py`, macOS).
- 법인 정보(법인명·로고·연락처·담당자·색)는 설정 파일 하나에서 읽습니다. 설정이 없으면 `○○회계법인` 같은 자리표시로 만듭니다.

## 설치

스킬 폴더에 이 저장소를 그대로 둡니다.

```bash
# Claude Code (개인)
git clone https://github.com/minsooparkk/proposal-deck-kr ~/.claude/skills/proposal-deck-kr
# Codex 등 Agent Skills 경로를 쓰는 에이전트
git clone https://github.com/minsooparkk/proposal-deck-kr ~/.agents/skills/proposal-deck-kr
```

새 대화에서 "우리 법인 서비스 소개서 PPT 만들어줘"처럼 요청하면 스킬이 쓰입니다. 같은 이름의 오래된 사본을 다른 스킬 경로에 함께 두지 않습니다.

## 자기 법인 정보 채우기

1. `assets/firm.example.json` 을 `assets/firm.json` 으로 복사해 채웁니다.
   - `firm_name`, `firm_name_en`, `website`, `email`
   - `logo`: 투명 배경 정사각 PNG 경로(스킬 폴더 기준)
   - `people`: 담당자별 `name`·`name_en`·`title`·`role`·`career`·`work`·`photo`(세로 2:3)·`crop`
   - `palette`: 색을 바꿀 때만(키는 예시 파일과 같게)
   - `profile`: 법인 소개 장의 수치·사무소. 기준일이 있는 출처에서 확인한 값만 넣습니다.
   다른 곳에 두려면 `PROPOSAL_DECK_FIRM=/경로/firm.json` 으로 지정합니다.
2. `references/firm-facts.template.md` 를 `references/firm-facts.md` 로 복사해 법인 현황·출처·담당자 약력·**대외 자료에 쓰지 않을 것**을 적습니다.
3. 원형 PPT의 자리표시 로고·사진은 자기 파일로 바꿔 쓰거나, 새 문서를 만들 때 바꿉니다.

`firm.json`·`firm-facts.md`·로고·사진은 법인 고유정보입니다. 이 저장소를 고쳐 다시 공개할 때는 넣지 않습니다(`.gitignore` 에 들어 있습니다).

## 필요한 환경

- Python 3.10 이상과 `python-pptx`. [uv](https://docs.astral.sh/uv/) 가 있으면 `uv run scripts/…` 가 스크립트 머리에 적힌 의존성을 임시로 받습니다.
- 미리보기: Pillow, Pretendard 글꼴(설치 또는 `PRETENDARD_DIR`).
- 실제 PowerPoint 검수: macOS 의 Microsoft PowerPoint, `pymupdf`. 없으면 이 검사만 건너뛰고 "PowerPoint 미확인"으로 안내합니다.

예제 만들기와 검사:

```bash
uv run scripts/examples/build_example_deck.py out/example.pptx
uv run scripts/check_deck.py out/example.pptx
uv run scripts/render_preview.py out/example.pptx out/preview --sheets
uv run scripts/powerpoint_check.py out/example.pptx --out out/qa --png
```

## 구성

```
SKILL.md                 작업 유형·진행 점검표·검수 고리·함정·참고 파일 색인
references/              편집·디자인·검수·제안서 흐름·보고서 흐름·문체 기준, 법인 사실 자료 틀
assets/                  원형 PPT 2벌, 미리보기, 자리표시 로고·사진, firm.example.json
scripts/                 deck_lib.py·sections.py(제작), check_deck.py·render_preview.py·powerpoint_check.py(검사), examples/
evals/                   평가 문항, 호출 판정 문항
agents/openai.yaml       Codex 표시 정보
```

## 라이선스

[라이선스 결정 대기 — 정해지면 LICENSE 파일과 함께 적습니다.]
