"""The transparent overlay and the settings page.

Qt lives only in this module. It is imported lazily from the plugin's window
and settings-page factories, so importing the package (for the validator, for
CI, for tests) never needs PySide6.

All tunables come from the plugin's settings dict (see ``DEFAULTS`` in
``__init__``); nothing visual is hard-coded here except pure rendering
mechanics (frame rate, fade curve, outline shape).
"""

from __future__ import annotations

import math
import random
import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nparseplus_sdk.ui import PluginWindow
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:  # pragma: no cover
    from . import CombatTextPlugin

# --- pure rendering mechanics (not user-facing) ---------------------------
FPS = 60
FADE_START = 0.55       # fraction of life after which a number begins to fade
MAX_NUMS = 120          # hard cap on numbers drawn at once
# Band along each edge reserved for the frameless window's own resize grip.
# Lane dragging never claims a press in here, or the edges become unusable.
RESIZE_MARGIN = 16
# Numbers fade out as they approach an edge instead of being clipped mid-glyph.
EDGE_FADE_MIN = 24.0

# Level-up flourish: how long the big "Ding! N!" lives, how much of that is
# spent growing, how large it gets relative to your main lane, and how many
# little ones scatter with it.
DING_MS = 1700.0
DING_GROW = 0.30
DING_FADE_FROM = 0.55
# How much of the window the finished Ding! spans, and the most of the
# height it may take. Sized by measuring the text, so it fills the overlay
# instead of guessing at a multiple and clipping.
DING_FILL_W = 0.92
DING_FILL_H = 0.72
DING_PARTICLES = 22

LANE_KINDS = (
    "out", "outns", "pet", "in", "inns", "outheal", "inheal", "outmiss", "inmiss"
)
HEAL_KINDS = ("outheal", "inheal")

# The 8 travel directions: (key, menu label, dx, dy). dy is +down (screen
# coords), so "up" is negative y. Diagonals are unit-normalised.
_D = 0.7071
DIRECTIONS = (
    ("up", "↑ Up", 0.0, -1.0),
    ("up_right", "↗ Up-right", _D, -_D),
    ("right", "→ Right", 1.0, 0.0),
    ("down_right", "↘ Down-right", _D, _D),
    ("down", "↓ Down", 0.0, 1.0),
    ("down_left", "↙ Down-left", -_D, _D),
    ("left", "← Left", -1.0, 0.0),
    ("up_left", "↖ Up-left", -_D, -_D),
)
DIR_VEC = {key: (dx, dy) for key, _label, dx, dy in DIRECTIONS}
# Short labels drawn on the overlay in setup mode.
LANE_LABELS = {
    "out": "YOUR HITS",
    "outns": "YOUR NON-MELEE",
    "pet": "PET",
    "in": "INCOMING",
    "inns": "INCOMING NON-MELEE",
    "outheal": "HEAL OUT",
    "inheal": "HEAL IN",
    "outmiss": "YOUR MISSES",
    "inmiss": "ENEMY MISSES",
}
# Friendlier labels for the settings-page rows.
LANE_ROW_LABELS = {
    "out": "Your hits",
    "outns": "Your non-melee",
    "pet": "Pet",
    "in": "Incoming",
    "inns": "Incoming non-melee",
    "outheal": "Outgoing healing",
    "inheal": "Incoming healing",
    "outmiss": "Your misses / avoids",
    "inmiss": "Enemy misses / avoids",
}


def _clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


def _grab_radius(size: float) -> float:
    """Pixel radius of a lane's drag handle / hit target, scaled to its font."""
    return max(34.0, float(size) * 0.6 + 20.0)



# Relative sizing: how many recent hits per lane feed the "typical hit"
# baseline, and how few will do before it is trusted. A median is used rather
# than a mean so one crit does not drag the whole lane's scale up.
BASELINE_SAMPLES = 60
BASELINE_MIN = 8

# Emphasis tiers. Relative mode grades a hit by how many times your typical
# hit it is; raw mode steps off multiples of the big-hit threshold.
RELATIVE_TIERS = (1.6, 2.6, 4.0)
ABSOLUTE_TIER_MULTIPLES = (1.0, 2.0, 4.0)


def _median(values: list[int]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if not n:
        return 0.0
    mid = n // 2
    if n % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0

_POP_MS = 130.0        # grow phase
_POP_SETTLE_MS = 110.0  # overshoot -> settle phase


def _pop_scale(age_ms: float) -> float:
    """Spawn 'pop': grow 0.6 -> 1.12, then settle 1.12 -> 1.0."""
    if age_ms < _POP_MS:
        return 0.6 + 0.52 * (age_ms / _POP_MS)
    settle = min(1.0, (age_ms - _POP_MS) / _POP_SETTLE_MS)
    return 1.12 - 0.12 * settle




def _outline_offsets(radius: int) -> tuple[tuple[int, int], ...]:
    """Ring of pen offsets out to ``radius`` px — a thicker ring per tier."""
    points: list[tuple[int, int]] = []
    for r in range(1, max(1, radius) + 1):
        points.extend(
            ((-r, 0), (r, 0), (0, -r), (0, r), (-r, -r), (r, r), (-r, r), (r, -r))
        )
    return tuple(points)


def _flare_rgb(base: tuple[int, int, int], age_ms: float) -> tuple[int, int, int]:
    """Killing-blow bloom: the outline starts near-white and decays to ``base``
    over ~350 ms, so the kill reads as a flash rather than a steady glow."""
    k = max(0.0, 1.0 - age_ms / 350.0)
    return tuple(min(255, int(c + (255 - c) * k)) for c in base)  # type: ignore[return-value]



@dataclass(slots=True)
class _Ding:
    """The one big level-up number. Kept apart from _Num because it grows far
    past the edge-fade margin and would otherwise erase itself."""

    text: str
    born: float


@dataclass(slots=True)
class _Num:
    text: str
    r: int
    g: int
    b: int
    size: int
    x: float          # fraction of width, centre of the text
    y0: float         # fraction of height, starting baseline
    born: float       # time.monotonic() at spawn
    tier: int         # 0 = ordinary; 1-3 = progressively louder flourish
    dx: float         # travel direction, x component (+right)
    dy: float         # travel direction, y component (+down)
    rise: float       # travel distance over the number's life (fraction)
    grav: float       # downward pull over its life (0 = straight drift)
    label: str        # special-attack word drawn above the number ("" = none)
    kind: str         # lane this number belongs to (killing-blow lookup)
    flare: bool = False   # killing blow: bright bloom + double lifetime
    flare_at: float = 0.0 # when the kill landed (bloom clock, separate from born)


class CombatTextWindow(PluginWindow):
    """Frameless, transparent overlay that animates floating damage numbers."""

    def __init__(self, wctx: Any, plugin: "CombatTextPlugin") -> None:
        super().__init__(wctx)
        self._plugin = plugin
        self._nums: list[_Num] = []
        # Guides on open: when asked for every time, or once on a fresh
        # install so lanes can be placed before any settings exist.
        self._setup = bool(plugin.get("setup_on_open")) or plugin.first_run()
        self._drag_lane: str | None = None
        # Recent hit sizes per lane, for the "relative" sizing baseline.
        # GUI thread only (written and read in _spawn), so no lock needed.
        self._recent: dict[str, deque[int]] = {}
        self._ding: _Ding | None = None
        self._ct_applied: bool | None = None

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self.setMinimumSize(160, 160)
        self._sync_click_through()

        self._timer = QTimer(self)
        self._timer.setInterval(int(1000 / FPS))
        self._timer.timeout.connect(self._on_frame)
        self._timer.start()

        # Come up on launch without a tray visit (opt-out via settings). A
        # short delay lets the host finish restoring window state first.
        if plugin.get("auto_show"):
            QTimer.singleShot(600, self._auto_show)

    def _auto_show(self) -> None:
        if not self.isVisible():
            self.show()

    # --- test sequence ------------------------------------------------------
    # A typical hit per lane, used to prime the relative-sizing baseline for a
    # test run, and multiplied per wave so the tiers are actually visible.
    TEST_TYPICAL = {
        "out": 90, "outns": 40, "pet": 45, "in": 67, "inns": 3,
        "outheal": 400, "inheal": 438,
    }
    TEST_WAVE_MULTIPLES = (1.0, 2.7, 5.0)

    def start_test(self) -> None:
        """Three waves of samples, one number per lane, 0.6 s apart.

        Relative sizing needs a lane's median before it means anything, and a
        three-wave test never reaches it — so a lane with no real history yet
        gets primed with plausible hits first. Lanes that HAVE seen real
        combat keep their own baseline, so a test never rewrites it.
        """
        for kind, typical in self.TEST_TYPICAL.items():
            recent = self._recent.setdefault(kind, deque(maxlen=BASELINE_SAMPLES))
            if len(recent) < BASELINE_MIN:
                recent.extend(
                    max(1, int(typical * random.uniform(0.8, 1.2)))
                    for _ in range(BASELINE_MIN + 2)
                )
        for i in range(3):
            QTimer.singleShot(i * 600, lambda wave=i: self._test_wave(wave))

    def _test_wave(self, wave: int) -> None:
        mult = self.TEST_WAVE_MULTIPLES[wave]
        amounts = {
            kind: max(1, int(typical * mult * random.uniform(0.9, 1.1)))
            for kind, typical in self.TEST_TYPICAL.items()
        }
        waves = {kind: (str(v), v) for kind, v in amounts.items()}
        # wave 2 is the crit
        if wave == 1:
            waves["out"] = (f"{amounts['out']}!", amounts["out"])
        waves["outmiss"] = (("miss", "riposte", "dodge")[wave], 0)
        waves["inmiss"] = (("dodge", "miss", "parry")[wave], 0)
        # wave 1 shows a special-attack label, wave 2 a Crippling Blow crit
        labels = {0: {"out": "backstab"}, 1: {"out": "Crippling Blow"}, 2: {"pet": "bash"}}
        for kind, (text, amount) in waves.items():
            self._spawn(text, amount, kind, labels.get(wave, {}).get(kind, ""))
        if wave == 2:
            QTimer.singleShot(260, lambda: self._mark_killing_blow("out"))

    def _sync_click_through(self) -> None:
        """Locked + click_through setting => pass clicks through to the game.
        Setup mode always stays interactive so lanes can be dragged."""
        want = (not self._setup) and bool(self._plugin.get("click_through"))
        if want == self._ct_applied:
            return
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, want)
        first = self._ct_applied is None
        self._ct_applied = want
        # On Windows this attribute becomes the WS_EX_TRANSPARENT window style,
        # which is only read when the native window is created. Flipping it on
        # a window that is already on screen changes nothing until the native
        # window is rebuilt — so setup mode would draw its rings while the
        # overlay stayed deaf to the mouse. Bounce it, keeping geometry.
        if not first and self.isVisible():
            geo = self.geometry()
            self.hide()
            self.show()
            self.setGeometry(geo)

    # --- animation loop ----------------------------------------------------
    def _on_frame(self) -> None:
        # Picks up live changes to the click_through setting and setup toggles.
        self._sync_click_through()
        if self.isVisible():
            for kind, text, amount, label in self._plugin.drain():
                self._spawn(text, amount, kind, label)
        self.update()


    def _damage_ratio(self, kind: str, amount: int) -> float:
        """This hit against the median of recent hits in the same lane.

        Returns 0.0 until the lane has enough history to be trusted. Records
        the sample as a side effect, so call it exactly once per hit.
        """
        recent = self._recent.setdefault(kind, deque(maxlen=BASELINE_SAMPLES))
        baseline = _median(list(recent)) if len(recent) >= BASELINE_MIN else 0.0
        recent.append(amount)
        return (amount / baseline) if baseline > 0 else 0.0

    def _size_factor(self, amount: int, ratio: float, mode: str) -> float:
        """Multiplier on the lane's base font size for this hit."""
        if mode == "off":
            return 1.0
        if mode == "relative" and ratio > 0.0:
            return _clamp(0.62 + 0.42 * ratio, 0.72, 2.0)
        # "By raw damage", and the stand-in until a lane has history: a fixed
        # curve on the raw number, which flattens out past 500.
        return 1.0 + min(amount, 500) / 830.0

    def _emphasis_tier(self, kind: str, amount: int, ratio: float, mode: str) -> int:
        """0 = ordinary, 1..3 = progressively louder flourish.

        Relative mode grades against your own recent hits, so the tiers keep
        meaning something as you level; otherwise they step off the raw
        big-hit threshold. Heals are never graded — a big heal is good news,
        not a crit.
        """
        if kind in HEAL_KINDS or amount <= 0:
            return 0
        if mode == "relative" and ratio > 0.0:
            edges = RELATIVE_TIERS
            value = ratio
        else:
            threshold = float(self._plugin.get("big_threshold") or 0)
            if threshold <= 0:
                return 0
            edges = tuple(threshold * m for m in ABSOLUTE_TIER_MULTIPLES)
            value = float(amount)
        tier = 0
        for edge in edges:
            if value >= edge:
                tier += 1
        return tier

    def _spawn(self, text: str, amount: int, kind: str, label: str = "") -> None:
        if amount == -2:
            self._start_ding(text)
            return
        if amount < 0:
            self._mark_killing_blow(kind)
            return
        p = self._plugin
        if not p.get(f"enabled_{kind}"):
            return
        size = float(p.get(f"size_{kind}"))
        if amount <= 0:
            # avoidance tick ("miss"/"dodge"/…): the lane's own size, never graded
            tier = 0
        else:
            mode = str(p.get("size_mode") or "relative")
            ratio = self._damage_ratio(kind, amount)
            size *= self._size_factor(amount, ratio, mode)
            tier = self._emphasis_tier(kind, amount, ratio, mode)
            # each tier adds a share of the configured big-hit bump, so the
            # flourish grows with the hit instead of flipping on at one number.
            size *= 1.0 + (float(p.get("big_scale")) - 1.0) * tier / 3.0
        rgb = p.get(f"color_{kind}") or [255, 255, 255]
        jitter = float(p.get("jitter_pct")) / 100.0
        vspread = float(p.get("vspread_pct")) / 100.0
        x = float(p.get(f"x_{kind}")) + random.uniform(-jitter, jitter)
        y0 = float(p.get(f"y_{kind}")) + random.uniform(-vspread, vspread)
        dx, dy = DIR_VEC.get(p.get(f"dir_{kind}") or "up", (0.0, -1.0))
        # Fan each number out within a cone around the lane's direction, and
        # vary its travel a little, so a burst reads as a spray rather than a
        # column of identical parallel numbers.
        spread = math.radians(float(p.get("spread_deg") or 0))
        if spread:
            angle = random.uniform(-spread, spread)
            cos_a, sin_a = math.cos(angle), math.sin(angle)
            dx, dy = dx * cos_a - dy * sin_a, dx * sin_a + dy * cos_a
        rise = float(p.get(f"dist_{kind}") or 42) / 100.0 * random.uniform(0.88, 1.12)
        grav = (
            float(p.get("gravity_pct") or 0) / 100.0
            if p.get(f"gravity_{kind}")
            else 0.0
        )
        self._nums.append(
            _Num(
                text=text,
                r=int(rgb[0]),
                g=int(rgb[1]),
                b=int(rgb[2]),
                size=int(size),
                x=x,
                y0=y0,
                born=time.monotonic(),
                tier=tier,
                dx=dx,
                dy=dy,
                rise=rise,
                grav=grav,
                label=label if p.get("show_special_labels") else "",
                kind=kind,
            )
        )
        if len(self._nums) > MAX_NUMS:
            del self._nums[: len(self._nums) - MAX_NUMS]



    def _start_ding(self, level: str) -> None:
        """Level up: one big number blooming from the centre, plus a scatter of
        small ones thrown in every direction. No lane and no ring — it borrows
        the whole overlay for a moment and then gets out of the way."""
        if not self._plugin.get("ding_flourish"):
            return
        now = time.monotonic()
        self._ding = _Ding(text=f"Ding! {level}!", born=now)
        rgb = self._plugin.get("ding_color") or [255, 214, 84]
        r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
        base = float(self._plugin.get("size_out") or 30) * 0.5
        for _ in range(DING_PARTICLES):
            angle = random.uniform(0.0, 2.0 * math.pi)
            self._nums.append(
                _Num(
                    text="Ding!",
                    r=r,
                    g=g,
                    b=b,
                    size=max(8, int(base * random.uniform(0.6, 1.25))),
                    x=0.5,
                    y0=0.5,
                    born=now,
                    tier=0,
                    dx=math.cos(angle),
                    dy=math.sin(angle),
                    rise=random.uniform(0.28, 0.62),
                    grav=random.uniform(0.0, 0.45),
                    label="",
                    kind="ding",
                )
            )
        if len(self._nums) > MAX_NUMS:
            del self._nums[: len(self._nums) - MAX_NUMS]

    def _mark_killing_blow(self, kind: str) -> None:
        """Flare + linger the newest number in ``kind``'s lane.

        The slain line lands after the damage line, so the killing blow is
        already drifting; this decorates it in place rather than adding text.
        """
        if not self._plugin.get("killing_blow"):
            return
        for n in reversed(self._nums):
            if n.kind == kind:
                n.flare = True
                n.flare_at = time.monotonic()
                if self._plugin.get("killing_blow_label"):
                    n.label = "Killing blow"
                return
    # --- painting ----------------------------------------------------------
    def paintEvent(self, event: Any) -> None:  # noqa: N802 (Qt override)
        p = self._plugin
        lifetime_ms = max(200.0, float(p.get("lifetime_s")) * 1000.0)
        big_color = tuple(p.get("big_color") or (255, 140, 0))
        pop = bool(p.get("spawn_pop"))
        label_size = max(6, int(p.get("label_size") or 12))

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = self.width()
        h = self.height()

        if self._setup:
            self._paint_guides(painter, w, h, big_color)

        now = time.monotonic()
        alive: list[_Num] = []
        for n in self._nums:
            age_ms = (now - n.born) * 1000.0
            # killing blows hang around twice as long
            life = lifetime_ms * 2.0 if n.flare else lifetime_ms
            if age_ms >= life:
                continue
            alive.append(n)
            t = age_ms / life
            # Ballistic path: launch along the lane direction, then let gravity
            # bend it. With gravity 0 this is the original straight drift.
            x_px = (n.x + n.dx * n.rise * t) * w
            y_px = (n.y0 + n.dy * n.rise * t + 0.5 * n.grav * t * t) * h
            if t <= FADE_START:
                alpha = 1.0
            else:
                alpha = max(0.0, 1.0 - (t - FADE_START) / (1.0 - FADE_START))
            size = max(6, int(n.size * _pop_scale(age_ms))) if pop else n.size
            # Fade toward the edges rather than letting the widget clip a glyph
            # in half — with gravity on, numbers routinely travel off the box.
            fade_margin = max(EDGE_FADE_MIN, size * 1.25)
            edge_dist = min(
                x_px, w - x_px, y_px - size * 0.75, h - y_px
            )
            if edge_dist < fade_margin:
                alpha *= _clamp(edge_dist / fade_margin, 0.0, 1.0)
            if alpha <= 0.01:
                continue
            if n.label:
                # sits just above the number, in the lane's colour
                self._draw_number(
                    painter,
                    n.label,
                    x_px,
                    y_px - size * 0.85,
                    label_size,
                    (n.r, n.g, n.b),
                    alpha,
                    0,
                    big_color,
                )
            self._draw_number(
                painter,
                n.text,
                x_px,
                y_px,
                size,
                (n.r, n.g, n.b),
                alpha,
                3 if n.flare else n.tier,
                _flare_rgb(big_color, (now - n.flare_at) * 1000.0) if n.flare else big_color,
            )
        self._nums = alive
        self._paint_ding(painter, w, h, now, big_color)
        painter.end()

    def _paint_ding(
        self,
        painter: QPainter,
        w: int,
        h: int,
        now: float,
        big_color: tuple[int, int, int],
    ) -> None:
        """The big level-up number: blooms out fast, holds, fades.

        Eased rather than linear so it swells and settles instead of snapping —
        celebratory, not a jump scare. Capped against the window so it cannot
        grow past what the overlay can show.
        """
        ding = self._ding
        if ding is None:
            return
        age = (now - ding.born) * 1000.0
        if age >= DING_MS:
            self._ding = None
            return
        t = age / DING_MS
        grow = 1.0 - (1.0 - min(1.0, t / DING_GROW)) ** 3
        # Measure the text at a reference size, then scale so it spans the
        # window rather than assuming a multiple that may not fit.
        probe = QFont()
        probe.setPixelSize(100)
        probe.setBold(True)
        painter.setFont(probe)
        advance = max(1, painter.fontMetrics().horizontalAdvance(ding.text))
        by_width = (w * DING_FILL_W) * 100.0 / advance
        target = max(12.0, min(by_width, h * DING_FILL_H))
        start = target * 0.12
        size = max(8, int(start + (target - start) * grow))
        if t <= DING_FADE_FROM:
            alpha = 0.94
        else:
            alpha = 0.94 * max(0.0, 1.0 - (t - DING_FADE_FROM) / (1.0 - DING_FADE_FROM))
        rgb = self._plugin.get("ding_color") or [255, 214, 84]
        self._draw_number(
            painter,
            ding.text,
            w / 2.0,
            h / 2.0 + size * 0.35,
            size,
            (int(rgb[0]), int(rgb[1]), int(rgb[2])),
            alpha,
            2,
            big_color,
        )


    def _draw_number(
        self,
        painter: QPainter,
        text: str,
        cx: float,
        y: float,
        size: int,
        rgb: tuple[int, int, int],
        alpha: float,
        tier: int = 0,
        big_color: tuple[int, int, int] = (255, 140, 0),
    ) -> None:
        font = QFont()
        font.setPixelSize(max(8, size))
        font.setBold(True)
        painter.setFont(font)
        tw = painter.fontMetrics().horizontalAdvance(text)
        x = int(cx - tw / 2)
        yi = int(y)
        if tier > 0:
            # The outline thickens and brightens with the tier, so a merely
            # good hit is a thin halo and a monster is a fat glow.
            outline = QColor(*big_color)
            outline.setAlphaF(min(1.0, alpha) * (0.72 + 0.09 * min(tier, 3)))
            offsets = _outline_offsets(min(tier, 3))
        else:
            outline = QColor(0, 0, 0)
            outline.setAlphaF(min(1.0, alpha) * 0.85)
            offsets = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1))
        painter.setPen(outline)
        for dx, dy in offsets:
            painter.drawText(x + dx, yi + dy, text)
        col = QColor(*rgb)
        col.setAlphaF(alpha)
        painter.setPen(col)
        painter.drawText(x, yi, text)

    def _paint_guides(
        self, painter: QPainter, w: int, h: int, big_color: tuple[int, int, int]
    ) -> None:
        p = self._plugin
        # Outer border: thick and bright, because it doubles as the thing you
        # aim at to resize the window.
        painter.setPen(QPen(QColor(255, 255, 255, 150), 3))
        painter.drawRect(1, 1, w - 3, h - 3)
        # Inner line marking how far in the resize band reaches — anywhere
        # between it and the border resizes rather than dragging a lane.
        m = RESIZE_MARGIN
        painter.setPen(QPen(QColor(255, 255, 255, 55), 1, Qt.PenStyle.DashLine))
        painter.drawRect(m, m, max(1, w - 2 * m), max(1, h - 2 * m))
        painter.setPen(QPen(QColor(120, 200, 255, 120), 2))
        painter.drawLine(w // 2, 0, w // 2, h)

        threshold = int(p.get("big_threshold"))
        samples = {
            "out": str(max(threshold, 150)),
            "outns": "40",
            "pet": "45",
            "in": "67",
            "inns": "3",
            "outheal": "399",
            "inheal": "438",
            "outmiss": "riposte",
            "inmiss": "miss",
        }
        for kind in LANE_KINDS:
            enabled = bool(p.get(f"enabled_{kind}"))
            cx = float(p.get(f"x_{kind}")) * w
            cy = float(p.get(f"y_{kind}")) * h
            rgb = tuple(p.get(f"color_{kind}") or (255, 255, 255))
            # grab handle (matches the drag hit target exactly)
            r = _grab_radius(float(p.get(f"size_{kind}")))
            ring = QColor(*rgb, 150 if enabled else 60)
            painter.setPen(QPen(ring, 3))
            painter.drawEllipse(int(cx - r), int(cy - r), int(2 * r), int(2 * r))
            # travel-direction indicator
            dx, dy = DIR_VEC.get(p.get(f"dir_{kind}") or "up", (0.0, -1.0))
            painter.setPen(QPen(QColor(*rgb, 190 if enabled else 70), 3))
            painter.drawLine(int(cx), int(cy), int(cx + dx * 34), int(cy + dy * 34))
            self._draw_number(
                painter,
                samples[kind],
                cx,
                cy,
                int(p.get(f"size_{kind}")),
                rgb,
                0.9 if enabled else 0.3,
                tier=2 if kind == "out" else 0,
                big_color=big_color,
            )
            label = LANE_LABELS[kind] + ("" if enabled else "  (off)")
            font = QFont()
            font.setPixelSize(11)
            painter.setFont(font)
            painter.setPen(QColor(*rgb, 170 if enabled else 80))
            painter.drawText(int(cx) - 34, int(cy) + 30, label)

        # clickable "hide guides" button (double-click also works, but a plain
        # button survives the window-move swallowing the second click)
        bx, by, bw, bh = self._hide_button_rect()
        painter.setPen(QColor(255, 255, 255, 150))
        painter.drawRect(bx, by, bw, bh)
        font = QFont()
        font.setPixelSize(11)
        painter.setFont(font)
        painter.drawText(bx + 10, by + bh - 7, "hide guides")
        painter.setPen(QColor(255, 255, 255, 120))
        painter.drawText(bx + bw + 12, by + bh - 7, "drag a lane to move it")

    def _hide_button_rect(self) -> tuple[int, int, int, int]:
        """(x, y, w, h) of the hide-guides button, bottom-left corner."""
        return (8, self.height() - 32, 86, 24)

    # --- interaction -------------------------------------------------------
    def _lane_at(self, px: float, py: float) -> str | None:
        w = max(1, self.width())
        h = max(1, self.height())
        # Generous nearest-wins hit test: a press anywhere NEAR a ring (ring
        # radius + 36 px, which also covers the label under it) grabs that
        # lane. Only presses far from every ring fall through to the window
        # move, so near-misses stop yanking the whole overlay around.
        best: str | None = None
        best_d2 = float("inf")
        for kind in LANE_KINDS:
            cx = float(self._plugin.get(f"x_{kind}")) * w
            cy = float(self._plugin.get(f"y_{kind}")) * h
            reach = _grab_radius(float(self._plugin.get(f"size_{kind}"))) + 36.0
            d2 = (px - cx) ** 2 + (py - cy) ** 2
            if d2 <= reach * reach and d2 < best_d2:
                best, best_d2 = kind, d2
        return best

    def _on_edge(self, px: float, py: float) -> bool:
        """Is this press in the band the window uses for edge resizing?"""
        m = RESIZE_MARGIN
        return (
            px <= m or py <= m or px >= self.width() - m or py >= self.height() - m
        )

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802 (Qt override)
        if self._setup and event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            # Edges belong to the resize grip, not to lane dragging.
            if self._on_edge(pos.x(), pos.y()):
                super().mousePressEvent(event)
                return
            bx, by, bw, bh = self._hide_button_rect()
            if bx <= pos.x() <= bx + bw and by <= pos.y() <= by + bh:
                self._setup = False
                self._sync_click_through()
                self.update()
                event.accept()
                return
            kind = self._lane_at(pos.x(), pos.y())
            if kind is not None:
                self._drag_lane = kind
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802 (Qt override)
        if self._drag_lane is not None:
            pos = event.position()
            # Keep rings clear of the resize band; a lane dropped under it
            # could never be picked up again, since the edge wins the press.
            w = max(1, self.width())
            h = max(1, self.height())
            pad_x = min(0.45, (RESIZE_MARGIN + 4) / w)
            pad_y = min(0.45, (RESIZE_MARGIN + 4) / h)
            x = _clamp(pos.x() / w, pad_x, 1.0 - pad_x)
            y = _clamp(pos.y() / h, pad_y, 1.0 - pad_y)
            self._plugin.set_lane_position(self._drag_lane, x, y, persist=False)
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802 (Qt override)
        if self._drag_lane is not None:
            kind = self._drag_lane
            self._plugin.set_lane_position(
                kind,
                float(self._plugin.get(f"x_{kind}")),
                float(self._plugin.get(f"y_{kind}")),
                persist=True,
            )
            self._drag_lane = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: Any) -> None:  # noqa: N802 (Qt override)
        self._setup = not self._setup
        self._sync_click_through()
        self.update()


    def is_setup(self) -> bool:
        return self._setup

    def toggle_setup(self) -> bool:
        """Turn the setup guides on or off, showing the overlay if it was
        hidden — guides you cannot see would be a strange thing to enable."""
        self._setup = not self._setup
        if self._setup and not self.isVisible():
            self.show()
            self.raise_()
        self._sync_click_through()
        self.update()
        return self._setup



# --------------------------------------------------------------------------
# Settings page
# --------------------------------------------------------------------------


class _ColorButton(QPushButton):
    """A swatch that opens the OS colour picker and remembers its RGB."""

    def __init__(self, rgb: Any, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rgb = [int(rgb[0]), int(rgb[1]), int(rgb[2])]
        self.setObjectName(name)
        self.setFixedSize(44, 24)
        self._refresh()
        self.clicked.connect(self._pick)

    def _refresh(self) -> None:
        r, g, b = self._rgb
        self.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); border: 1px solid #888; border-radius: 4px;"
        )

    def _pick(self) -> None:
        chosen = QColorDialog.getColor(QColor(*self._rgb), self, "Pick a colour")
        if chosen.isValid():
            self._rgb = [chosen.red(), chosen.green(), chosen.blue()]
            self._refresh()

    def rgb(self) -> list[int]:
        return list(self._rgb)

    def set_rgb(self, rgb: Any) -> None:
        self._rgb = [int(rgb[0]), int(rgb[1]), int(rgb[2])]
        self._refresh()


def _spin(name: str, lo: int, hi: int, value: int, parent: QWidget) -> QSpinBox:
    box = QSpinBox(parent)
    box.setObjectName(name)
    box.setRange(lo, hi)
    box.setValue(int(value))
    return box


def _dspin(name: str, lo: float, hi: float, step: float, value: float, parent: QWidget) -> QDoubleSpinBox:
    box = QDoubleSpinBox(parent)
    box.setObjectName(name)
    box.setRange(lo, hi)
    box.setSingleStep(step)
    box.setValue(float(value))
    return box


def _dir_combo(name: str, value: str, parent: QWidget) -> QComboBox:
    combo = QComboBox(parent)
    combo.setObjectName(name)
    for key, label, _dx, _dy in DIRECTIONS:
        combo.addItem(label, key)
    idx = combo.findData(value)
    combo.setCurrentIndex(idx if idx >= 0 else 0)
    return combo


def _apply_values_to_page(page: QWidget, values: dict) -> None:
    """Push a settings dict back into the page's controls (used by Reset)."""
    for name, val in values.items():
        cb = page.findChild(QCheckBox, name)
        if cb is not None:
            if isinstance(val, bool):
                cb.setChecked(val)
            continue
        sp = page.findChild(QSpinBox, name)
        if sp is not None:
            try:
                sp.setValue(int(val))
            except (TypeError, ValueError):
                pass
            continue
        ds = page.findChild(QDoubleSpinBox, name)
        if ds is not None:
            try:
                ds.setValue(float(val))
            except (TypeError, ValueError):
                pass
            continue
        color = page.findChild(QPushButton, name)
        if color is not None and hasattr(color, "set_rgb"):
            color.set_rgb(val)
            continue
        combo = page.findChild(QComboBox, name)
        if combo is not None:
            i = combo.findData(val)
            if i >= 0:
                combo.setCurrentIndex(i)


def build_settings_page(parent: QWidget | None, values: dict, plugin: Any = None) -> QWidget:
    page = QWidget(parent)
    root = QVBoxLayout(page)

    # --- Open / test / reset ----------------------------------------------
    _tray_note = (
        "Open the overlay once from the nParse+ tray menu (look for "
        "“Floating Combat Text”), then these will work."
    )
    setup_btn = QPushButton(page)
    test_btn = QPushButton("Test", page)
    reset_btn = QPushButton("Reset to defaults", page)
    setup_btn.setToolTip(
        "Show the lane rings and the centre guide so lanes can be dragged and "
        "the window resized. The overlay ignores the mouse when this is off."
    )

    def _refresh_buttons() -> None:
        in_setup = bool(plugin is not None and plugin.setup_active())
        setup_btn.setText("Leave setup mode" if in_setup else "Setup mode")

    def _toggle_setup() -> None:
        if plugin is None or plugin.toggle_setup() is None:
            QMessageBox.information(page, "Floating Combat Text", _tray_note)
            return
        _refresh_buttons()

    def _test() -> None:
        if not (plugin is not None and plugin.request_test()):
            QMessageBox.information(page, "Floating Combat Text", _tray_note)
            return
        _refresh_buttons()

    def _reset() -> None:
        if plugin is None:
            return
        if (
            QMessageBox.question(
                page,
                "Floating Combat Text",
                "Reset all Floating Combat Text settings to their defaults?",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        plugin.reset_defaults()
        _apply_values_to_page(page, plugin.settings())

    setup_btn.clicked.connect(_toggle_setup)
    test_btn.clicked.connect(_test)
    reset_btn.clicked.connect(_reset)
    _refresh_buttons()
    buttons = QHBoxLayout()
    buttons.addWidget(setup_btn)
    buttons.addWidget(test_btn)
    buttons.addStretch(1)
    buttons.addWidget(reset_btn)
    root.addLayout(buttons)

    # --- presets: named layouts you can keep or share ----------------------
    save_btn = QPushButton("Save preset…", page)
    load_btn = QPushButton("Load preset…", page)

    def _preset_default() -> str:
        d = plugin.preset_dir() if plugin is not None else None
        return str(d) if d else ""

    def _save_preset() -> None:
        if plugin is None:
            return
        base = _preset_default()
        start = (base + "/my-layout.json") if base else "my-layout.json"
        path, _f = QFileDialog.getSaveFileName(page, "Save preset", start, "JSON (*.json)")
        if not path:
            return
        err = plugin.export_settings(path, read_settings_page(page))
        if err:
            QMessageBox.warning(page, "Floating Combat Text", f"Could not save preset:\n{err}")

    def _load_preset() -> None:
        if plugin is None:
            return
        path, _f = QFileDialog.getOpenFileName(
            page, "Load preset", _preset_default(), "JSON (*.json)"
        )
        if not path:
            return
        err = plugin.import_settings(path)
        if err:
            QMessageBox.warning(page, "Floating Combat Text", f"Could not load preset:\n{err}")
            return
        _apply_values_to_page(page, plugin.settings())

    save_btn.clicked.connect(_save_preset)
    load_btn.clicked.connect(_load_preset)
    presets_row = QHBoxLayout()
    presets_row.addWidget(save_btn)
    presets_row.addWidget(load_btn)
    presets_row.addStretch(1)
    root.addLayout(presets_row)

    # --- Lanes -------------------------------------------------------------
    lanes = QGroupBox("Lanes", page)
    grid = QGridLayout(lanes)
    grid.setHorizontalSpacing(14)
    grid.setVerticalSpacing(10)
    grid.setColumnStretch(4, 1)
    for col, head in enumerate(("", "On", "Colour", "Size", "Move", "Grav", "Travel %")):
        grid.addWidget(QLabel(head, lanes), 0, col)
    for row, kind in enumerate(LANE_KINDS, start=1):
        grid.addWidget(QLabel(LANE_ROW_LABELS[kind], lanes), row, 0)

        enable = QCheckBox(lanes)
        enable.setObjectName(f"enabled_{kind}")
        enable.setChecked(bool(values.get(f"enabled_{kind}", True)))
        grid.addWidget(enable, row, 1)

        grid.addWidget(
            _ColorButton(values.get(f"color_{kind}", [255, 255, 255]), f"color_{kind}", lanes),
            row,
            2,
        )
        grid.addWidget(_spin(f"size_{kind}", 8, 96, int(values.get(f"size_{kind}", 28)), lanes), row, 3)
        grid.addWidget(_dir_combo(f"dir_{kind}", str(values.get(f"dir_{kind}", "up")), lanes), row, 4)
        grav = QCheckBox(lanes)
        grav.setObjectName(f"gravity_{kind}")
        grav.setChecked(bool(values.get(f"gravity_{kind}", False)))
        grav.setToolTip("Let gravity arc this lane's numbers downward.")
        grid.addWidget(grav, row, 5)
        grid.addWidget(
            _spin(f"dist_{kind}", 0, 100, int(values.get(f"dist_{kind}", 42)), lanes), row, 6
        )
    hint = QLabel(
        "“Move” is the direction numbers drift; “Travel” is how far (percent "
        "of the window). To position a lane, open the overlay in setup mode "
        "and drag its ring — placements save automatically.",
        lanes,
    )
    hint.setWordWrap(True)
    grid.addWidget(hint, len(LANE_KINDS) + 1, 0, 1, 7)
    root.addWidget(lanes)

    # --- Big hits ----------------------------------------------------------
    big = QGroupBox("Big hits", page)
    bform = QFormLayout(big)
    bform.addRow("Threshold (points)", _spin("big_threshold", 0, 100000, int(values.get("big_threshold", 150)), big))
    bform.addRow("Extra size ×", _dspin("big_scale", 1.0, 3.0, 0.05, float(values.get("big_scale", 1.35)), big))
    bform.addRow("Glow colour", _ColorButton(values.get("big_color", [255, 140, 0]), "big_color", big))
    root.addWidget(big)

    # --- Motion and feel ---------------------------------------------------
    motion = QGroupBox("Motion and feel", page)
    mform = QFormLayout(motion)
    mform.addRow("Lifetime (sec)", _dspin("lifetime_s", 0.3, 6.0, 0.1, float(values.get("lifetime_s", 1.5)), motion))
    mform.addRow("Horizontal spread (%)", _spin("jitter_pct", 0, 50, int(values.get("jitter_pct", 8)), motion))
    mform.addRow("Vertical spread (%)", _spin("vspread_pct", 0, 60, int(values.get("vspread_pct", 10)), motion))
    size_mode = QComboBox(motion)
    size_mode.setObjectName("size_mode")
    for key, text in (
        ("relative", "Relative to your typical hit"),
        ("absolute", "By raw damage"),
        ("off", "All the same size"),
    ):
        size_mode.addItem(text, key)
    idx = size_mode.findData(str(values.get("size_mode", "relative")))
    size_mode.setCurrentIndex(idx if idx >= 0 else 0)
    mform.addRow("Size by damage", size_mode)
    mform.addRow(
        "Direction spread (°)", _spin("spread_deg", 0, 90, int(values.get("spread_deg", 18)), motion)
    )
    mform.addRow(
        "Gravity (%)", _spin("gravity_pct", 0, 300, int(values.get("gravity_pct", 0)), motion)
    )
    gravity_note = QLabel(
        "How hard gravity pulls, for the lanes with Grav ticked above. 0 is a "
        "straight drift; higher values arc the numbers over and drop them. For a "
        "fountain, point a lane up, widen the spread, tick Grav, and try about 120.",
        motion,
    )
    gravity_note.setWordWrap(True)
    mform.addRow(gravity_note)
    pop = QCheckBox("Pop numbers in when they appear", motion)
    pop.setObjectName("spawn_pop")
    pop.setChecked(bool(values.get("spawn_pop", True)))
    mform.addRow(pop)
    ct = QCheckBox("Click through the overlay when not in setup mode", motion)
    ct.setObjectName("click_through")
    ct.setChecked(bool(values.get("click_through", True)))
    mform.addRow(ct)
    labels_cb = QCheckBox(
        "Label special attacks (backstab, bash, kick, Crippling Blow)", motion
    )
    labels_cb.setObjectName("show_special_labels")
    labels_cb.setChecked(bool(values.get("show_special_labels", True)))
    mform.addRow(labels_cb)
    mform.addRow(
        "Label size (px)", _spin("label_size", 6, 48, int(values.get("label_size", 12)), motion)
    )
    ding = QCheckBox("Ding! flourish on level up", motion)
    ding.setObjectName("ding_flourish")
    ding.setChecked(bool(values.get("ding_flourish", True)))
    ding.setToolTip(
        "When you gain a level, a big Ding! blooms from the centre of the "
        "overlay with a scatter of small ones."
    )
    mform.addRow(ding)
    mform.addRow(
        "Ding! colour", _ColorButton(values.get("ding_color", [255, 214, 84]), "ding_color", motion)
    )
    kb = QCheckBox("Flare the killing blow (your kills and your pet's)", motion)
    kb.setObjectName("killing_blow")
    kb.setChecked(bool(values.get("killing_blow", True)))
    mform.addRow(kb)
    kbl = QCheckBox("…and label it “Killing blow”", motion)
    kbl.setObjectName("killing_blow_label")
    kbl.setChecked(bool(values.get("killing_blow_label", True)))
    mform.addRow(kbl)
    auto = QCheckBox("Open the overlay automatically when nParse+ starts", motion)
    auto.setObjectName("auto_show")
    auto.setChecked(bool(values.get("auto_show", True)))
    mform.addRow(auto)
    setup = QCheckBox("Show setup guides every time the window opens", motion)
    setup.setObjectName("setup_on_open")
    setup.setChecked(bool(values.get("setup_on_open", False)))
    mform.addRow(setup)
    root.addWidget(motion)

    root.addStretch(1)
    return page


def read_settings_page(page: QWidget) -> dict:
    out: dict[str, Any] = {}
    for name in (
        "enabled_out", "enabled_outns", "enabled_pet", "enabled_in", "enabled_inns",
        "enabled_outheal", "enabled_inheal", "enabled_outmiss", "enabled_inmiss",
        "gravity_out", "gravity_outns", "gravity_pet", "gravity_in", "gravity_inns",
        "gravity_outheal", "gravity_inheal", "gravity_outmiss", "gravity_inmiss",
        "spawn_pop", "click_through", "setup_on_open",
        "auto_show", "show_special_labels", "killing_blow", "killing_blow_label",
        "ding_flourish",
    ):
        w = page.findChild(QCheckBox, name)
        if w is not None:
            out[name] = bool(w.isChecked())
    for name in (
        "size_out", "size_outns", "size_pet", "size_in", "size_inns",
        "size_outheal", "size_inheal", "size_outmiss", "size_inmiss",
        "dist_out", "dist_outns", "dist_pet", "dist_in", "dist_inns",
        "dist_outheal", "dist_inheal", "dist_outmiss", "dist_inmiss",
        "big_threshold", "jitter_pct", "vspread_pct", "label_size", "spread_deg",
        "gravity_pct",
    ):
        w = page.findChild(QSpinBox, name)
        if w is not None:
            out[name] = int(w.value())
    for name in ("big_scale", "lifetime_s"):
        w = page.findChild(QDoubleSpinBox, name)
        if w is not None:
            out[name] = float(w.value())
    # Note: lane positions (x_*/y_*) are intentionally NOT read here — they are
    # set by dragging in the overlay and would otherwise be clobbered on Apply.
    for name in (
        "color_out", "color_outns", "color_pet", "color_in", "color_inns",
        "color_outheal", "color_inheal", "color_outmiss", "color_inmiss",
        "big_color", "ding_color",
    ):
        w = page.findChild(QPushButton, name)
        if w is not None and hasattr(w, "rgb"):
            out[name] = w.rgb()
    for kind in LANE_KINDS:
        name = f"dir_{kind}"
        w = page.findChild(QComboBox, name)
        if w is not None:
            out[name] = w.currentData()
    mode = page.findChild(QComboBox, "size_mode")
    if mode is not None:
        out["size_mode"] = mode.currentData()
    return out
