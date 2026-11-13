"""대표가 읽는 글의 작은 약속.

WORK 뒤는 '작업용'(텔레그램에서 눌러야 펼쳐지는 인용)으로 올라간다. 경로·명령·오류 원문은 여기에.
QUIET 한 줄만 있는 예약 답은 올리지 않는다(알릴 것이 없을 때).
"""

WORK = "⟦작업용⟧"
QUIET = "⟦알릴 것 없음⟧"


def work(detail):
    detail = str(detail or "").strip()
    return f"\n{WORK}\n{detail}" if detail else ""


def split(text):
    """(대표가 읽는 위쪽, 작업용 아래쪽)."""
    text = str(text or "")
    if WORK in text:
        top, _, rest = text.partition(WORK)
        return top.strip(), rest.strip()
    return text.strip(), ""


def quiet(text):
    return str(text or "").strip() == QUIET or (QUIET in str(text or "") and len(str(text).strip()) < 40)


def cut(s, n):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"
