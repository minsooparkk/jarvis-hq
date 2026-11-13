# /// script
# requires-python = ">=3.10"
# dependencies = ["python-pptx>=1.0"]
# ///
# -*- coding: utf-8 -*-
"""가상 예시: 초기 기업 회계·세무 관리 서비스 소개서 (19장). 도구 사용법을 보여주는 예시다.

  uv run scripts/examples/build_example_deck.py OUT.pptx
  PROPOSAL_DECK_FIRM=assets/firm.example.json uv run scripts/examples/build_example_deck.py OUT.pptx

법인 정보는 설정(assets/firm.json, 또는 PROPOSAL_DECK_FIRM)에서 읽고, 없으면 '○○회계법인' 같은 자리표시로 만든다.
법인·서비스·수치는 모두 가상이며 세무 판단의 근거가 아니다. 새 문서의 내용 기준으로 쓰지 않는다.
"""
import os, sys
if len(sys.argv) != 2 or sys.argv[1] in ('-h', '--help') or not sys.argv[1].lower().endswith('.pptx'):
    sys.stderr.write(__doc__ + '\n사용법: build_example_deck.py OUT.pptx  (OUT 은 새로 만들 .pptx 경로, 같은 이름이 있으면 덮어씀)\n')
    sys.exit(0 if len(sys.argv) == 2 and sys.argv[1] in ('-h', '--help') else 2)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
try:
    from deck_lib import *
    from sections import *
except ImportError as e:
    sys.exit(f'의존성 없음: {e}. `uv run scripts/examples/build_example_deck.py OUT.pptx` 로 실행하거나 python-pptx 를 설치한 환경을 쓴다.')

NOTE = '가상 예시 문서입니다. 실제 문서에서는 출처·근거를 노트가 아닌 별도 근거 자료에 보존합니다.'
F = FIRM['firm_name']

cover('FOR EARLY-STAGE COMPANIES', '초기 기업 회계·세무 관리 서비스',
      [('설립 직후부터 투자 유치까지, ', {}), ('장부와 신고', {'color': C['blue2'], 'bold': True}), ('를 함께 정리합니다.', {})],
      notes=NOTE)
contents([('01', '초기 기업 회계의 특성', 3), ('02', '신고 중심 업무의 한계', 6), ('03', '업무 수행 방식', 8),
          ('04', '담당자 및 업무 절차', 11), ('05', f'{F} 소개', 14)])

# ---------------- 01 (본문 2장)
divider('01', '초기 기업 회계의 특성', [])
s = slide('EARLY-STAGE ACCOUNTING', '초기 기업 회계의 특성(1/2) - 주요 검토 영역',
          '설립 초기의 회계 처리 기준은 이후 결산과 투자 검토에 그대로 이어지므로, 처음부터 함께 정리해야 합니다.', NOTE)
ch4 = [('회계 처리 기준', '매출 인식 시점과 비용 처리 기준을 정하지 않으면, 결산 때마다 같은 거래를 다르게 처리할 수 있습니다.'),
       ('증빙 관리', '법인카드·계좌 거래와 증빙을 맞추는 규칙이 없으면 결산과 신고 준비에 시간이 많이 듭니다.'),
       ('투자 유치 대비', '투자 검토에서 요구하는 재무자료는 일정한 기준으로 작성된 장부를 전제로 합니다.'),
       ('신고 일정 관리', '원천세·부가가치세·법인세 신고 일정을 놓치면 가산세 부담이 생길 수 있습니다.')]
gw = (CW - 0.3) / 2; gh = 2.05
for i, (k, v) in enumerate(ch4):
    x = L + (i % 2) * (gw + 0.3); y = 2.3 + (i // 2) * (gh + 0.2)
    box(s, x, y, gw, gh, fill=C['surface']); box(s, x, y, 0.07, gh, fill=C['blue'])
    txt(s, x + 0.4, y + 0.25, gw - 0.8, 0.4, k, size=18, bold=True, color=C['ink'])
    txt(s, x + 0.4, y + 0.78, gw - 0.8, 1.15, v, size=13.5, color=C['text'], spacing=1.3)

s = slide('COMPANY LIFECYCLE', '초기 기업 회계의 특성(2/2) - 단계별 검토 사항',
          '설립 단계의 결정이 이후 결산·신고와 투자 검토에 영향을 주므로, 단계별로 확인할 사항을 미리 정리해야 합니다.', NOTE)
cols4 = [('설립', ['회계 처리 기준 수립', '증빙 관리 규칙', '급여·원천세 설정', '신고 일정표 작성']),
         ('성장', ['월 결산 체계', '부가가치세 신고', '비용 처리 점검', '내부 보고 자료']),
         ('투자 유치', ['재무제표 정비', '실사 자료 준비', '주요 계약 검토', '주식 보상 처리']),
         ('사후 관리', ['정기 결산 검토', '법인세 신고', '세무 위험 점검', '다음 단계 계획'])]
cw4 = (CW - 3 * 0.3) / 4
for i, (hd, its) in enumerate(cols4):
    x = L + i * (cw4 + 0.3)
    box(s, x, 2.3, cw4, 0.6, fill=C['dark'] if i < 3 else C['blue'])
    txt(s, x + 0.25, 2.3, cw4 - 0.4, 0.6, hd, size=15, bold=True, color=C['white'], anchor=MSO_ANCHOR.MIDDLE, align=PP_ALIGN.CENTER)
    box(s, x, 2.9, cw4, 3.85, fill=C['surface'])
    for j, it in enumerate(its):
        y = 3.1 + j * 0.9
        txt(s, x + 0.25, y, 0.4, 0.3, f'{j+1}', size=12, bold=True, color=C['blue'])
        txt(s, x + 0.6, y, cw4 - 0.8, 0.7, it, size=14, color=C['ink'], spacing=1.2)
        if j < 3: line(s, x + 0.25, y + 0.72, cw4 - 0.5, C['line'])
    if i < 3: arrow(s, x + cw4 + 0.03, 2.6, x + cw4 + 0.27, C['grey'])

# ---------------- 02 (본문 1장: 진행 번호 없음)
divider('02', '신고 중심 업무의 한계', [])
s = slide('REVIEW REQUIREMENTS', '신고 중심 업무의 한계 - 검토상 한계와 영향',
          '신고서 작성 중심으로 업무를 수행하는 경우, 결산 기준과 투자 대비 자료는 별도 검토가 필요합니다.', NOTE)
rows = [('신고서 작성 중심', '결산 기준 정비가 뒤로 밀림', '같은 거래의 처리 기준이 해마다 달라짐'),
        ('연 1회 결산', '월별 재무 현황 파악이 늦음', '경영 판단에 쓸 자료가 부족함'),
        ('증빙 사후 수집', '누락 증빙 확인에 시간이 듦', '비용 인정 여부 검토가 늦어짐'),
        ('투자 시점 일괄 정리', '과거 장부 재작성 부담', '실사 대응 기간이 길어짐')]
table(s, L, 2.3, [3.3, 4.35, 4.183], ['업무 수행 방식', '검토상 한계', '영향'], rows, row_h=0.97, head_h=0.5, size=14,
      style=lambda i, j, v: (j != 1, C['blue'] if j == 2 else (C['ink'] if j == 0 else C['text'])))

# ---------------- 03 (본문 2장)
divider('03', '업무 수행 방식', [])
s = slide('SERVICE SCOPE', '업무 수행 방식(1/2) - 주요 제공 서비스',
          '의뢰 시점과 협의한 범위에 따라 결산 기준 정비, 월 결산, 투자 대비 자료 작성을 수행할 예정입니다.', NOTE)
svc = [('결산 기준 정비', '설립 초기 회계 기준이 필요한 기업', ['매출·비용 처리 기준 수립', '증빙 관리 규칙 정리', '계정과목 체계 정비'], '회계 처리 기준서'),
       ('월 결산·신고', '매월 재무 현황을 확인하려는 기업', ['월 결산과 내부 보고', '원천세·부가가치세 신고', '법인세 신고 준비'], '월간 재무 보고서와 신고서'),
       ('투자 대비 자료', '투자 유치를 준비하는 기업', ['재무제표 정비', '실사 요청 자료 준비', '주요 쟁점 사전 점검'], '실사 대응 자료 목록')]
sw_ = (CW - 2 * 0.3) / 3
for i, (nm, who, its, out) in enumerate(svc):
    x = L + i * (sw_ + 0.3)
    box(s, x, 2.3, sw_, 4.45, fill=C['surface'])
    txt(s, x + 0.35, 2.52, 1, 0.3, f'0{i+1}', size=13, bold=True, color=C['blue'])
    txt(s, x + 0.35, 2.85, sw_ - 0.7, 0.45, nm, size=18, bold=True, color=C['ink'])
    txt(s, x + 0.35, 3.35, sw_ - 0.7, 0.7, who, size=12.5, color=C['muted'], spacing=1.25)
    line(s, x + 0.35, 4.1, sw_ - 0.7, C['line'])
    txt(s, x + 0.35, 4.22, sw_ - 0.6, 1.3, ['· ' + t for t in its], size=13.5, color=C['ink'], spacing=1.2, after=4)
    box(s, x, 5.65, sw_, 1.1, fill=C['pale'])
    txt(s, x + 0.35, 5.75, sw_ - 0.7, 0.3, '결과물', size=11.5, bold=True, color=C['blue'])
    txt(s, x + 0.35, 6.05, sw_ - 0.7, 0.6, out, size=13, bold=True, color=C['ink'], spacing=1.2)

s = slide('ROLES', '업무 수행 방식(2/2) - 역할과 자료 흐름',
          '회사가 거래 자료를 공유하면 담당 회계사가 결산·신고에 반영하고, 검토 결과를 회사와 협의할 예정입니다.', NOTE)
nw = 4.67; gap = CW - 2 * nw
for i, (who, its) in enumerate([(F, ['결산 기준 정비', '월 결산·신고', '검토 결과 보고']),
                                ('고객사 담당자', ['거래 자료·증빙 공유', '기준 변경 사항 공유', '보고 내용 확인'])]):
    x = L + i * (nw + gap)
    box(s, x, 2.35, nw, 2.55, fill=C['surface'])
    txt(s, x + 0.35, 2.7, nw - 0.7, 0.45, who, size=20, bold=True, color=C['ink'], align=PP_ALIGN.CENTER)
    line(s, x + 0.35, 3.35, nw - 0.7, C['line'])
    txt(s, x + 0.35, 3.58, nw - 0.7, 1.2, its, size=13.5, color=C['text'], spacing=1.2, after=4, align=PP_ALIGN.CENTER)
arrow(s, L + nw + 0.15, 3.45, L + nw + gap - 0.15, C['blue'])
txt(s, L + nw + 0.1, 3.0, gap - 0.2, 0.4, '자료 공유·검토 협의', size=13, bold=True, color=C['blue'], align=PP_ALIGN.CENTER)
box(s, L, 5.3, CW, 1.2, fill=C['pale'])
txt(s, L + 0.4, 5.3, CW - 0.8, 1.2, '업무 범위와 전달 일정은 의뢰 시점에 협의하여 계약서에 명시할 예정입니다.', size=15, bold=True,
    color=C['ink'], anchor=MSO_ANCHOR.MIDDLE, align=PP_ALIGN.CENTER)

# ---------------- 04 (본문 2장)
divider('04', '담당자 및 업무 절차', [])
team_slide('YOUR TEAM', '담당자 및 업무 절차(1/2) - 담당 회계사',
           '담당 회계사가 결산 기준 정비부터 신고와 투자 대비 자료까지 직접 수행할 예정입니다.', notes=NOTE)
next_step('NEXT STEP', '담당자 및 업무 절차(2/2) - 업무 진행 절차',
          '업무 범위와 보수를 먼저 안내하고, 협의가 끝나면 계약 후 업무를 진행할 예정입니다.',
          [('문의·기본 정보', '회사 현황과 요청 사항을 확인하고 필요한 자료를 안내할 예정입니다.'),
           ('범위·보수 안내', '수행할 업무와 보수, 결과 전달 방식과 일정을 정할 예정입니다.'),
           ('자료 확인·수행', '받은 자료로 결산·신고를 수행하고 누락 자료를 안내할 예정입니다.'),
           ('결과·후속 안내', '검토 결과를 전달하고 후속 조치를 안내할 예정입니다.')],
          info=['회사명과 설립일, 업종', '최근 결산·신고 현황', '요청하는 업무와 희망 일정'], notes=NOTE)

# ---------------- 05 법인 소개 (본문 4장)
firm_profile('05')
thank_you()
save(sys.argv[1], '초기 기업 회계·세무 관리 서비스 소개 (가상 예시)')
