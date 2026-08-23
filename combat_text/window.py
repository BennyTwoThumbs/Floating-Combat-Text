"""The transparent overlay and the settings page.

Qt lives only in this module. It is imported lazily from the plugin's window
and settings-page factories, so importing the package (for the validator, for
CI, for tests) never needs PySide6.

All tunables come from the plugin's settings dict (see ``DEFAULTS`` in
``__init__``); nothing visual is hard-coded here except pure rendering
mechanics (frame rate, fade curve, outline shape).
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nparseplus_sdk.ui import PluginWindow
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
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

LANE_KINDS = ("out", "outns", "pet", "in", "inns", "outheal", "inheal")
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
}


def _clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


def _grab_radius(size: float) -> float:
    """Pixel radius of a lane's drag handle / hit target, scaled to its font."""
    return max(34.0, float(size) * 0.6 + 20.0)


_POP_MS = 130.0        # grow phase
_POP_SETTLE_MS = 110.0  # overshoot -> settle phase


def _pop_scale(age_ms: float) -> float:
    """Spawn 'pop': grow 0.6 -> 1.12, then settle 1.12 -> 1.0."""
    if age_ms < _POP_MS:
        return 0.6 + 0.52 * (age_ms / _POP_MS)
    settle = min(1.0, (age_ms - _POP_MS) / _POP_SETTLE_MS)
    return 1.12 - 0.12 * settle


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
    big: bool         # big hit -> orange outline + extra size
    dx: float         # travel direction, x component (+right)
    dy: float         # travel direction, y component (+down)


class CombatTextWindow(PluginWindow):
    """Frameless, transparent overlay that animates floating damage numbers."""

    def __init__(self, wctx: Any, plugin: "CombatTextPlugin") -> None:
        super().__init__(wctx)
        self._plugin = plugin
        self._nums: list[_Num] = []
        self._setup = bool(plugin.get("setup_on_open"))
        self._drag_lane: str | None = None
        self._ct_applied: bool | None = None

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self.setMinimumSize(160, 160)
        self._sync_click_through()

        self._timer = QTimer(self)
        self._timer.setInterval(int(1000 / FPS))
        self._timer.timeout.connect(self._on_frame)
        self._timer.start()

    def _sync_click_through(self) -> None:
        """Locked + click_through setting => pass clicks through to the game.
        Setup mode always stays interactive so lanes can be dragged."""
        want = (not self._setup) and bool(self._plugin.get("click_through"))
        if want != self._ct_applied:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, want)
            self._ct_applied = want

    # --- animation loop ----------------------------------------------------
    def _on_frame(self) -> None:
        # Picks up live changes to the click_through setting and setup toggles.
        self._sync_click_through()
        if self.isVisible():
            for amount, kind in self._plugin.drain():
                self._spawn(amount, kind)
        self.update()

    def _spawn(self, amount: int, kind: str) -> None:
        p = self._plugin
        if not p.get(f"enabled_{kind}"):
            return
        size = float(p.get(f"size_{kind}"))
        if p.get("scale_with_damage"):
            size *= 1.0 + min(amount, 500) / 830.0
        big = kind not in HEAL_KINDS and amount >= int(p.get("big_threshold"))
        if big:
            size *= float(p.get("big_scale"))
        rgb = p.get(f"color_{kind}") or [255, 255, 255]
        jitter = float(p.get("jitter_pct")) / 100.0
        vspread = float(p.get("vspread_pct")) / 100.0
        x = float(p.get(f"x_{kind}")) + random.uniform(-jitter, jitter)
        y0 = float(p.get(f"y_{kind}")) + random.uniform(-vspread, vspread)
        dx, dy = DIR_VEC.get(p.get(f"dir_{kind}") or "up", (0.0, -1.0))
        self._nums.append(
            _Num(
                text=str(amount),
                r=int(rgb[0]),
                g=int(rgb[1]),
                b=int(rgb[2]),
                size=int(size),
                x=x,
                y0=y0,
                born=time.monotonic(),
                big=big,
                dx=dx,
                dy=dy,
            )
        )
        if len(self._nums) > MAX_NUMS:
            del self._nums[: len(self._nums) - MAX_NUMS]

    # --- painting ----------------------------------------------------------
    def paintEvent(self, event: Any) -> None:  # noqa: N802 (Qt override)
        p = self._plugin
        lifetime_ms = max(200.0, float(p.get("lifetime_s")) * 1000.0)
        rise = float(p.get("rise_pct")) / 100.0
        big_color = tuple(p.get("big_color") or (255, 140, 0))
        pop = bool(p.get("spawn_pop"))

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
            if age_ms >= lifetime_ms:
                continue
            alive.append(n)
            t = age_ms / lifetime_ms
            x_px = (n.x + n.dx * rise * t) * w
            y_px = (n.y0 + n.dy * rise * t) * h
            if t <= FADE_START:
                alpha = 1.0
            else:
                alpha = max(0.0, 1.0 - (t - FADE_START) / (1.0 - FADE_START))
            size = max(6, int(n.size * _pop_scale(age_ms))) if pop else n.size
            self._draw_number(
                painter, n.text, x_px, y_px, size, (n.r, n.g, n.b), alpha, n.big, big_color
            )
        self._nums = alive
        painter.end()

    def _draw_number(
        self,
        painter: QPainter,
        text: str,
        cx: float,
        y: float,
        size: int,
        rgb: tuple[int, int, int],
        alpha: float,
        big: bool = False,
        big_color: tuple[int, int, int] = (255, 140, 0),
    ) -> None:
        font = QFont()
        font.setPixelSize(max(8, size))
        font.setBold(True)
        painter.setFont(font)
        tw = painter.fontMetrics().horizontalAdvance(text)
        x = int(cx - tw / 2)
        yi = int(y)
        if big:
            outline = QColor(*big_color)
            outline.setAlphaF(min(1.0, alpha) * 0.95)
            offsets = (
                (-2, 0), (2, 0), (0, -2), (0, 2),
                (-2, -2), (2, 2), (-2, 2), (2, -2),
                (-1, 0), (1, 0), (0, -1), (0, 1),
            )
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
        painter.setPen(QColor(255, 255, 255, 40))
        painter.drawRect(0, 0, w - 1, h - 1)
        painter.setPen(QColor(120, 200, 255, 70))
        painter.drawLine(w // 2, 0, w // 2, h)

        threshold = int(p.get("big_threshold"))
        samples = {
            "out": max(threshold, 150),
            "outns": 40,
            "pet": 45,
            "in": 67,
            "inns": 3,
            "outheal": 399,
            "inheal": 438,
        }
        for kind in LANE_KINDS:
            enabled = bool(p.get(f"enabled_{kind}"))
            cx = float(p.get(f"x_{kind}")) * w
            cy = float(p.get(f"y_{kind}")) * h
            rgb = tuple(p.get(f"color_{kind}") or (255, 255, 255))
            amount = samples[kind]
            # grab handle (matches the drag hit target exactly)
            r = _grab_radius(float(p.get(f"size_{kind}")))
            ring = QColor(*rgb, 90 if enabled else 35)
            painter.setPen(ring)
            painter.drawEllipse(int(cx - r), int(cy - r), int(2 * r), int(2 * r))
            # travel-direction indicator
            dx, dy = DIR_VEC.get(p.get(f"dir_{kind}") or "up", (0.0, -1.0))
            painter.setPen(QColor(*rgb, 150 if enabled else 60))
            painter.drawLine(int(cx), int(cy), int(cx + dx * 30), int(cy + dy * 30))
            self._draw_number(
                painter,
                str(amount),
                cx,
                cy,
                int(p.get(f"size_{kind}")),
                rgb,
                0.9 if enabled else 0.3,
                big=(kind == "out" and amount >= threshold),
                big_color=big_color,
            )
            label = LANE_LABELS[kind] + ("" if enabled else "  (off)")
            font = QFont()
            font.setPixelSize(11)
            painter.setFont(font)
            painter.setPen(QColor(*rgb, 170 if enabled else 80))
            painter.drawText(int(cx) - 34, int(cy) + 30, label)

        font = QFont()
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255, 120))
        painter.drawText(8, h - 8, "drag a lane to move it · double-click to hide this guide")

    # --- interaction -------------------------------------------------------
    def _lane_at(self, px: float, py: float) -> str | None:
        w = max(1, self.width())
        h = max(1, self.height())
        # Nearest lane whose grab-ring the cursor is inside wins, so overlapping
        # rings still resolve to one lane rather than the first in list order.
        best: str | None = None
        best_d2 = float("inf")
        for kind in LANE_KINDS:
            cx = float(self._plugin.get(f"x_{kind}")) * w
            cy = float(self._plugin.get(f"y_{kind}")) * h
            radius = _grab_radius(float(self._plugin.get(f"size_{kind}")))
            d2 = (px - cx) ** 2 + (py - cy) ** 2
            if d2 <= radius * radius and d2 < best_d2:
                best, best_d2 = kind, d2
        return best

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802 (Qt override)
        if self._setup and event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            kind = self._lane_at(pos.x(), pos.y())
            if kind is not None:
                self._drag_lane = kind
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802 (Qt override)
        if self._drag_lane is not None:
            pos = event.position()
            x = _clamp(pos.x() / max(1, self.width()), 0.0, 1.0)
            y = _clamp(pos.y() / max(1, self.height()), 0.0, 1.0)
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

    def enter_setup_and_show(self) -> None:
        """Show the overlay, raise it, and turn on the setup guides."""
        self._setup = True
        self._sync_click_through()
        self.show()
        self.raise_()
        self.activateWindow()
        self.update()


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
        "Open the overlay first from the nParse+ tray menu (look for "
        "“Floating Combat Text”), then try this again."
    )
    open_btn = QPushButton("Open overlay in setup mode", page)
    test_btn = QPushButton("Test", page)
    reset_btn = QPushButton("Reset to defaults", page)

    def _open() -> None:
        if not (plugin is not None and plugin.open_overlay()):
            QMessageBox.information(page, "Floating Combat Text", _tray_note)

    def _test() -> None:
        if not (plugin is not None and plugin.request_test()):
            QMessageBox.information(page, "Floating Combat Text", _tray_note)

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

    open_btn.clicked.connect(_open)
    test_btn.clicked.connect(_test)
    reset_btn.clicked.connect(_reset)
    buttons = QHBoxLayout()
    buttons.addWidget(open_btn)
    buttons.addWidget(test_btn)
    buttons.addStretch(1)
    buttons.addWidget(reset_btn)
    root.addLayout(buttons)

    # --- Lanes -------------------------------------------------------------
    lanes = QGroupBox("Lanes", page)
    grid = QGridLayout(lanes)
    grid.setHorizontalSpacing(14)
    grid.setVerticalSpacing(10)
    grid.setColumnStretch(4, 1)
    for col, head in enumerate(("", "On", "Colour", "Size", "Move")):
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
    hint = QLabel(
        "“Move” is the direction numbers drift; distance is set by Travel "
        "distance under Motion. To position a lane, open the overlay in setup "
        "mode and drag its ring — placements save automatically.",
        lanes,
    )
    hint.setWordWrap(True)
    grid.addWidget(hint, len(LANE_KINDS) + 1, 0, 1, 5)
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
    mform.addRow("Travel distance (%)", _spin("rise_pct", 0, 100, int(values.get("rise_pct", 42)), motion))
    mform.addRow("Horizontal spread (%)", _spin("jitter_pct", 0, 50, int(values.get("jitter_pct", 8)), motion))
    mform.addRow("Vertical spread (%)", _spin("vspread_pct", 0, 60, int(values.get("vspread_pct", 10)), motion))
    scale = QCheckBox("Scale size with damage", motion)
    scale.setObjectName("scale_with_damage")
    scale.setChecked(bool(values.get("scale_with_damage", True)))
    mform.addRow(scale)
    pop = QCheckBox("Pop numbers in when they appear", motion)
    pop.setObjectName("spawn_pop")
    pop.setChecked(bool(values.get("spawn_pop", True)))
    mform.addRow(pop)
    ct = QCheckBox("Click through the overlay when not in setup mode", motion)
    ct.setObjectName("click_through")
    ct.setChecked(bool(values.get("click_through", True)))
    mform.addRow(ct)
    setup = QCheckBox("Show setup guides when the window opens", motion)
    setup.setObjectName("setup_on_open")
    setup.setChecked(bool(values.get("setup_on_open", True)))
    mform.addRow(setup)
    root.addWidget(motion)

    root.addStretch(1)
    return page


def read_settings_page(page: QWidget) -> dict:
    out: dict[str, Any] = {}
    for name in (
        "enabled_out", "enabled_outns", "enabled_pet", "enabled_in", "enabled_inns",
        "enabled_outheal", "enabled_inheal",
        "scale_with_damage", "spawn_pop", "click_through", "setup_on_open",
    ):
        w = page.findChild(QCheckBox, name)
        if w is not None:
            out[name] = bool(w.isChecked())
    for name in (
        "size_out", "size_outns", "size_pet", "size_in", "size_inns",
        "size_outheal", "size_inheal",
        "big_threshold", "rise_pct", "jitter_pct", "vspread_pct",
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
        "color_outheal", "color_inheal", "big_color",
    ):
        w = page.findChild(QPushButton, name)
        if w is not None and hasattr(w, "rgb"):
            out[name] = w.rgb()
    for kind in LANE_KINDS:
        name = f"dir_{kind}"
        w = page.findChild(QComboBox, name)
        if w is not None:
            out[name] = w.currentData()
    return out
