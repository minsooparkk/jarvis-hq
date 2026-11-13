"""cron 다섯 칸(분 시 일 월 요일) 맞추기. 일(day)과 요일은 둘 다 맞아야 한다(AND)."""


def cron_field(spec, value, lo, hi):
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/")
            step = int(s)
        if part == "*":
            a, b = lo, hi
        elif "-" in part:
            a, b = map(int, part.split("-"))
        else:
            a = b = int(part)
        if a <= value <= b and (value - a) % step == 0:
            return True
    return False


def cron_match(expr, t):
    m, h, dom, mon, dow = str(expr).split()
    wd = (t.weekday() + 1) % 7  # 일=0
    return (cron_field(m, t.minute, 0, 59) and cron_field(h, t.hour, 0, 23) and cron_field(dom, t.day, 1, 31)
            and cron_field(mon, t.month, 1, 12)
            and (cron_field(dow, wd, 0, 7) or (wd == 0 and cron_field(dow, 7, 0, 7))))


def valid(expr):
    try:
        parts = str(expr).split()
        if len(parts) != 5:
            return False
        from datetime import datetime
        cron_match(expr, datetime(2026, 1, 1))
        return True
    except (ValueError, TypeError):
        return False
