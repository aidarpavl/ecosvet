"""Распознавание окон и дверей на стенах помещения по условным обозначениям плана.

Условные знаки (как на планах школы):
  • стена  — сплошная насыщенно-синяя полоса;
  • окно   — участок стены без синего, светлый, с тонкими серыми параллельными линиями;
  • дверь  — белый разрыв в синей стене (проём между двумя синими блоками).

Алгоритм: для каждой стороны контура помещения ищем линию стены (максимум синего в полосе ±12 px),
затем вдоль стены классифицируем каждый столбик поперёк стены: W — стена, O — окно, G — разрыв.
Серии O длиной ≥ 6 px → окно; серии G длиной 5–40 px между участками стены → дверь.
"""
from __future__ import annotations

import json
from functools import lru_cache

import numpy as np
from PIL import Image

SEARCH = 12      # полуширина полосы поиска стены, px
MIN_WIN = 6      # минимальная длина окна, px
DOOR_MIN, DOOR_MAX = 5, 40


@lru_cache(maxsize=8)
def _classes(path: str, mtime: float) -> np.ndarray:
    a = np.asarray(Image.open(path).convert("RGB")).astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(axis=2), a.min(axis=2)
    cls = np.zeros(r.shape, np.uint8)                              # 0 — прочее
    cls[(b > 100) & (b - np.maximum(r, g) > 50)] = 1               # 1 — синий (стена)
    cls[(mx - mn < 45) & (mn > 80) & (mx < 222)] = 2               # 2 — серый (линии окна / текст)
    cls[mn >= 222] = 3                                             # 3 — белый
    # жёлтые/красные стены (план Астана 127) тоже считаем стеной
    cls[(r > 150) & (g > 130) & (b < 110)] = 1
    cls[(r > 170) & (g < 90) & (b < 90)] = 1
    return cls


def _runs(s: str):
    out, i = [], 0
    while i < len(s):
        j = i
        while j < len(s) and s[j] == s[i]:
            j += 1
        out.append((s[i], i, j))
        i = j
    return out


def _edge(cls: np.ndarray, horizontal: bool, fixed: int, a: int, b: int) -> dict | None:
    """Анализ одной стороны. fixed — координата стороны (y для горизонтальной, x для вертикальной)."""
    H, W = cls.shape
    a, b = max(a + 3, 0), min(b - 3, (W if horizontal else H) - 1)
    if b - a < 8:
        return None
    lo, hi = max(fixed - SEARCH, 0), min(fixed + SEARCH, (H if horizontal else W) - 1)
    strip = cls[lo:hi + 1, a:b] if horizontal else cls[a:b, lo:hi + 1].T   # (смещение, вдоль)
    blue = (strip == 1).mean(axis=1)
    if blue.max() < 0.15:
        return None                                   # стены нет (открытая сторона)
    best = int(blue.argmax())
    band = [i for i in range(len(blue)) if blue[i] >= 0.4 * blue[best] and abs(i - best) <= 7]
    t0, t1 = min(band), max(band)
    t0, t1 = max(t0 - 1, 0), min(t1 + 1, len(blue) - 1)
    wall = strip[t0:t1 + 1]
    th = wall.shape[0]
    seq = []
    for col in wall.T:
        nb, ng, nw = (col == 1).sum(), (col == 2).sum(), (col == 3).sum()
        if nb >= max(2, 0.35 * th):
            seq.append("W")
        elif ng >= 2 and nb <= 1:
            seq.append("O")
        elif nw >= th - 1:
            seq.append("G")
        else:
            seq.append("?")
    s = "".join(seq)
    runs = _runs(s)
    windows, doors = [], []
    for k, (c, i, j) in enumerate(runs):
        n = j - i
        if c == "O" and n >= MIN_WIN:
            windows.append((i, j))
        if c in "G?" and DOOR_MIN <= n <= DOOR_MAX:
            left = runs[k - 1][0] if k > 0 else ""
            right = runs[k + 1][0] if k + 1 < len(runs) else ""
            if left == "W" and right == "W" and c == "G":
                doors.append((i, j))
    pos = lo + (t0 + t1) / 2

    def seg(i, j):
        return [a + i, pos, a + j, pos] if horizontal else [pos, a + i, pos, a + j]

    return {"windows": [seg(i, j) for i, j in windows], "doors": [seg(i, j) for i, j in doors]}


def detect(image_path: str, box) -> dict:
    """Окна и двери по контуру (x1, y1, x2, y2). Возвращает сегменты в пикселях плана."""
    from pathlib import Path
    p = Path(image_path)
    cls = _classes(str(p), p.stat().st_mtime)
    x1, y1, x2, y2 = [int(round(v)) for v in (min(box[0], box[2]), min(box[1], box[3]),
                                                max(box[0], box[2]), max(box[1], box[3]))]
    res = {"windows": [], "doors": []}
    for e in (_edge(cls, True, y1, x1, x2), _edge(cls, True, y2, x1, x2),
              _edge(cls, False, x1, y1, y2), _edge(cls, False, x2, y1, y2)):
        if e:
            res["windows"] += e["windows"]
            res["doors"] += e["doors"]
    return res


def seg_len(s) -> float:
    return float(np.hypot(s[2] - s[0], s[3] - s[1]))


def summarize(res: dict, area_m2: float, box) -> dict:
    """Перевод в метры: масштаб берётся из площади помещения и площади контура."""
    px_area = abs((box[2] - box[0]) * (box[3] - box[1]))
    m_per_px = (area_m2 / px_area) ** 0.5 if px_area > 0 and area_m2 > 0 else 0.0
    win_len = sum(seg_len(s) for s in res["windows"]) * m_per_px
    return {"win_count": len(res["windows"]), "win_len": round(win_len, 2), "door_count": len(res["doors"]),
            "openings": json.dumps(res)}
