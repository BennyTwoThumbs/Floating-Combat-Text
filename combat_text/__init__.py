"""Floating Combat Text — MMO-style damage numbers for nParse+.

A transparent overlay that pops a rising, fading number for every hit it sees
in the EQ log:

* your own hits         — white,  left side
* your pet's hits       — orange, smaller, lower-left
* damage done to you    — red,    right side

Line the window up over your character and it reads like a modern MMO's
floating combat text. It only ever reads the log file: no number is invented,
and nothing is ever sent anywhere.

What the Project 1999 log does and does not carry (so the numbers stay honest):

* Your melee AND your spell / proc / DoT damage both arrive tagged as yours.
  The game logs spell damage as an attacker-less ``... was hit by non-melee``
  line, which EQTool — and therefore nParse+ — attributes to you, so your
  nukes show up in white alongside your swings.
* Incoming damage is captured for melee (``<mob> hits YOU ...``). Incoming
  spell nukes and DoT ticks are logged in a form the host does not turn into a
  damage event, so red numbers are essentially your melee mitigation view.
* Pet hits are attributed only after the pet has identified itself to you at
  least once this session (on summon, ``/pet attack``, ``/pet follow`` …).
  Before that its name is unknown, so its hits are skipped rather than guessed.

Threading, per the SDK contract: :meth:`activate` runs on the GUI thread; the
event callbacks run on the log-driver thread and only ever append to a
lock-guarded buffer; the window drains that buffer on its own Qt timer. Qt is
imported nowhere in this module — only lazily inside the window factory — so
this file stays importable for ``nparseplus-plugin validate`` and for any
environment that has the SDK but not PySide6.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from typing import Any

from nparseplus_sdk import (
    NParsePlugin,
    PluginContext,
    PluginMeta,
    PluginSettingsPageSpec,
    PluginWindowSpec,
)

__all__ = ["CombatTextPlugin", "create_plugin", "DEFAULTS"]

# Hits buffered between GUI frames. At 60 fps the window drains this ~16 ms;
# the cap only matters if the window is closed while combat rages on.
MAX_PENDING = 400

# Every tunable, with its default. This is the whole schema: the settings page
# reads and writes these keys, the overlay reads them each frame, and they are
# saved verbatim through ``ctx.storage``. Colours are [r, g, b]; x/y are
# fractions of the window (0..1); sizes are pixels. Editing here only changes
# the defaults a fresh install starts from.
DEFAULTS: dict[str, Any] = {
    # per-lane enable.  out/in = melee; outns/inns = non-melee (damage
    # shields, nukes, procs); pet = your pet's hits.
    "enabled_out": True,
    "enabled_outns": True,
    "enabled_pet": True,
    "enabled_in": True,
    "enabled_inns": True,
    "enabled_outheal": True,
    "enabled_inheal": True,
    # per-lane colour
    "color_out": [255, 255, 255],
    "color_outns": [120, 225, 255],   # your DS / non-melee: cyan
    "color_pet": [255, 168, 40],
    "color_in": [236, 64, 58],
    "color_inns": [205, 120, 235],    # incoming DS / non-melee: purple
    "color_outheal": [90, 220, 110],  # healing you cast: green
    "color_inheal": [150, 235, 180],  # healing on you: soft green
    # per-lane base font size (px). Non-melee lanes are smaller, like pet.
    "size_out": 34,
    "size_outns": 18,
    "size_pet": 22,
    "size_in": 30,
    "size_inns": 18,
    "size_outheal": 24,
    "size_inheal": 22,
    # per-lane anchor position (fraction of the window)
    "x_out": 0.30,
    "y_out": 0.60,
    "x_outns": 0.42,
    "y_outns": 0.48,
    "x_pet": 0.24,
    "y_pet": 0.85,
    "x_in": 0.72,
    "y_in": 0.60,
    "x_inns": 0.60,
    "y_inns": 0.48,
    "x_outheal": 0.50,
    "y_outheal": 0.34,
    "x_inheal": 0.50,
    "y_inheal": 0.72,
    # per-lane travel direction (one of the 8 compass keys in window.DIRECTIONS:
    # up / up_right / right / down_right / down / down_left / left / up_left)
    "dir_out": "up",
    "dir_outns": "up",
    "dir_pet": "up",
    "dir_in": "up",
    "dir_inns": "up",
    "dir_outheal": "down",
    "dir_inheal": "down",
    # big-hit ("crit") emphasis
    "big_threshold": 150,
    "big_scale": 1.35,
    "big_color": [255, 140, 0],
    # per-lane travel distance (% of window a number drifts over its life)
    "dist_out": 42,
    "dist_outns": 42,
    "dist_pet": 42,
    "dist_in": 42,
    "dist_inns": 42,
    "dist_outheal": 55,
    "dist_inheal": 55,
    "dist_outmiss": 30,
    "dist_inmiss": 30,
    # motion & feel
    "scale_with_damage": True,
    "lifetime_s": 1.5,
    "jitter_pct": 8,        # horizontal spread (% of window)
    "vspread_pct": 10,      # vertical spread (% of window) so stacked hits separate
    "setup_on_open": False,  # guides still appear once on a true first run
    "auto_show": True,       # open the overlay on launch without a tray visit
    "spawn_pop": True,      # numbers pop in (scale up then settle)
    "click_through": True,  # when NOT in setup mode, let clicks pass to the game
    # Miss/avoidance ticks get their own two lanes so they can be placed apart
    # from the damage numbers. Off by default: chatter some people won't want.
    "enabled_outmiss": False,
    "enabled_inmiss": False,
    "color_outmiss": [200, 200, 200],   # your swings that failed: grey
    "color_inmiss": [255, 130, 120],    # incoming swings that failed: soft red
    "size_outmiss": 16,
    "size_inmiss": 16,
    "x_outmiss": 0.36,
    "y_outmiss": 0.72,
    "x_inmiss": 0.64,
    "y_inmiss": 0.72,
    "dir_outmiss": "up",
    "dir_inmiss": "up",
}


class CombatTextPlugin(NParsePlugin):
    meta = PluginMeta(
        id="floating-combat-text",
        name="Floating Combat Text",
        version="1.10.1",
        description=(
            "MMO-style floating combat text for nParse+: your hits, pet, "
            "incoming, non-melee / damage-shields, and healing as colour-coded "
            "numbers that pop, drift, and fade. Reads the log only; sends nothing."
        ),
        author="BennyTwoThumbs (Forsure MyDude)",
        homepage="https://github.com/BennyTwoThumbs/Floating-Combat-Text",
        requires_sdk=">=1.0,<2",
        update_url=(
            "https://raw.githubusercontent.com/BennyTwoThumbs/"
            "Floating-Combat-Text/main/index.json"
        ),
    )

    def __init__(self) -> None:
        self._ctx: PluginContext | None = None
        # The driver thread writes _pending and _pet_name; the GUI thread reads
        # them. Neither is touched off this lock.
        self._lock = threading.Lock()
        # Each entry is (kind, text, amount). amount drives sizing/big-hit;
        # amount 0 marks a miss/avoidance tick whose word is in text.
        self._pending: deque[tuple[str, str, int]] = deque(maxlen=MAX_PENDING)
        self._pet_name: str = ""
        # Crit announcements ("<name> Scores a critical hit!(49)") arrive just
        # BEFORE their damage line. Each entry is (amount, monotonic time); an
        # outgoing hit matching one within 1.5 s renders with a trailing "!".
        self._crits: deque[tuple[int, float]] = deque(maxlen=8)
        # Settings live here and are only ever touched on the GUI thread (the
        # settings page and the overlay's own drags/paints). The driver-thread
        # callbacks never read them.
        self._settings: dict[str, Any] = dict(DEFAULTS)
        # Set once the host builds the overlay via the factory; lets the
        # settings-page button bring it forward and into setup mode.
        self._window: Any = None
        # True when no stored settings existed at activate — a fresh install.
        # The overlay uses it to show the setup guides exactly once.
        self._first_run = False

    # --- lifecycle ---------------------------------------------------------
    def activate(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._load_settings(ctx)
        ctx.add_window(
            PluginWindowSpec(
                key="combat-text",
                title="Floating Combat Text",
                factory=self._make_window,
                # Tall-ish and offset right of centre by default so there is
                # room for the incoming (right) lane; you will drag it over
                # your character on first run.
                default_geometry=(760, 240, 480, 480),
            )
        )
        ctx.add_settings_page(
            PluginSettingsPageSpec(
                title="Floating Combat Text",
                builder=self._build_settings_page,
                apply=self._apply_settings_page,
            )
        )
        # Typed events are the happy path. If this SDK build does not export
        # them (older/newer surface), fall back to the raw line feed so the
        # plugin still works instead of silently showing nothing.
        try:
            self._subscribe_typed(ctx)
            ctx.logger.info("floating-combat-text: using typed damage/pet events")
        except ImportError:
            ctx.logger.warning(
                "floating-combat-text: typed events unavailable; "
                "falling back to the raw line feed"
            )
            self._subscribe_lines(ctx)

    # --- event wiring ------------------------------------------------------
    def _subscribe_typed(self, ctx: PluginContext) -> None:
        from nparseplus_sdk.events import DamageEvent, PetEvent

        def on_damage(ev: Any) -> None:
            self._record(
                getattr(ev, "attacker_name", ""),
                getattr(ev, "target_name", ""),
                int(getattr(ev, "damage_done", 0) or 0),
                getattr(ev, "damage_type", ""),
            )

        def on_pet(ev: Any) -> None:
            name = getattr(ev, "pet_name", "") or ""
            if name:
                with self._lock:
                    self._pet_name = name

        ctx.subscribe(DamageEvent, on_damage)
        ctx.subscribe(PetEvent, on_pet)

        # The host turns "<mob> was hit by non-melee" into a DamageEvent (your
        # DS / nukes / procs), but NOT the self line "You were hit by non-melee
        # for N damage" — its parser matches "was", not "were". Parse that one
        # line ourselves off the raw feed so a mob's damage shield (incoming
        # non-melee) gets counted. No overlap with DamageEvent, so no
        # double-counting.
        import re as _re

        from nparseplus_sdk.events import LineEvent

        self_ds = _re.compile(
            r"^You were hit by non-melee for (?P<d>\d+)(?: point(?:s)? of)? damage"
        )
        # Heals carry their amount, but the host has no heal parser, so we read
        # these two lines ourselves.
        heal_out = _re.compile(
            r"^You have healed (?P<t>[\w` ]+) for (?P<d>\d+)(?: point(?:s)? of)? damage"
        )
        heal_in = _re.compile(
            r"^(?P<a>[\w`'\-. ]+?) has healed you for (?P<d>\d+)(?: point(?:s)? of)? damage"
        )
        # Misses: the host publishes them as zero-damage events (no avoidance
        # word), so the word is read straight off the line instead.
        miss_out = _re.compile(r"^You try to \w+ [\w` ]+, but (?P<rest>.+)")
        miss_in = _re.compile(r"^[\w`'\-. ]+? tries to \w+ YOU, but (?P<rest>.+)")
        avoid_word = _re.compile(r"\b(dodge|parr|riposte|block|absorb)", _re.IGNORECASE)
        # e.g. "Forsure Scores a critical hit!(49)" / "You deliver a critical blast!(196)"
        crit_re = _re.compile(
            r"^(?P<n>[\w`'\-. ]+?) (?:scores? a critical hit!|delivers? a critical blast!)"
            r"\s*\((?P<d>\d+)\)",
            _re.IGNORECASE,
        )

        def on_line(ev: Any) -> None:
            msg = getattr(ev, "line", "") or ""
            if "critical" in msg:
                m = crit_re.match(msg)
                if m:
                    self._record_crit(m.group("n"), int(m.group("d")))
                    return
            if "non-melee" in msg:
                m = self_ds.match(msg)
                if m:
                    self._record("", "You", int(m.group("d")), "non-melee")
                return
            if "healed" in msg:
                m = heal_out.match(msg)
                if m:
                    self._record("You", m.group("t"), int(m.group("d")), "heal")
                    return
                m = heal_in.match(msg)
                if m:
                    self._record(m.group("a"), "you", int(m.group("d")), "heal")
                return
            if ", but " in msg:
                m = miss_out.match(msg)
                incoming = m is None
                if m is None:
                    m = miss_in.match(msg)
                if m:
                    w = avoid_word.search(m.group("rest"))
                    if w:
                        # Lanes are actor-based: the DEFENDER's dodge/parry/
                        # riposte/block lands in the defender's lane.
                        word = {"parr": "parry"}.get(w.group(1).lower(), w.group(1).lower())
                        self._record_miss("out" if incoming else "in", word)
                    else:
                        # a plain whiff belongs to the attacker
                        self._record_miss("in" if incoming else "out", "miss")

        ctx.subscribe(LineEvent, on_line)

    def _subscribe_lines(self, ctx: PluginContext) -> None:
        """Best-effort fallback: parse the timestamp-stripped line ourselves.

        Mirrors the host's DamageParser closely enough for combat text. Only
        used when ``nparseplus_sdk.events`` lacks the typed classes.
        """
        import re

        from nparseplus_sdk.events import LineEvent

        verbs = (
            r"hits|slashes|pierces|crushes|claws|bites|stings|mauls|gores|"
            r"punches|kicks|backstabs|bashes|slices|strikes|smashes"
        )
        you_verbs = (
            r"hit|slash|pierce|crush|claw|bite|sting|maul|gore|punch|kick|"
            r"backstab|bash|slice|strike|smash"
        )
        you_hit = re.compile(
            rf"^You (?:{you_verbs}) (?P<t>[\w` ]+) for (?P<d>\d+) point"
        )
        other_hit = re.compile(
            rf"^(?P<a>[\w`'\-. ]+?) (?:{verbs}) (?P<t>[\w` ]+) for (?P<d>\d+) point"
        )
        non_melee = re.compile(r"^(?P<t>[\w` ]+) was hit by non-melee for (?P<d>\d+) point")
        self_ds = re.compile(
            r"^You were hit by non-melee for (?P<d>\d+)(?: point(?:s)? of)? damage"
        )
        heal_out = re.compile(
            r"^You have healed (?P<t>[\w` ]+) for (?P<d>\d+)(?: point(?:s)? of)? damage"
        )
        heal_in = re.compile(
            r"^(?P<a>[\w`'\-. ]+?) has healed you for (?P<d>\d+)(?: point(?:s)? of)? damage"
        )
        miss_out = re.compile(r"^You try to \w+ [\w` ]+, but (?P<rest>.+)")
        miss_in = re.compile(r"^[\w`'\-. ]+? tries to \w+ YOU, but (?P<rest>.+)")
        avoid_word = re.compile(r"\b(dodge|parr|riposte|block|absorb)", re.IGNORECASE)
        crit_re = re.compile(
            r"^(?P<n>[\w`'\-. ]+?) (?:scores? a critical hit!|delivers? a critical blast!)"
            r"\s*\((?P<d>\d+)\)",
            re.IGNORECASE,
        )
        pet_id = re.compile(
            r"^(?P<p>[\w` ]+) (?:tells you, 'Attacking"
            r"|says 'At your service Master"
            r"|says 'Following you, Master"
            r"|says 'Guarding with my life"
            r"|says 'Changing position, Master"
            r"|says 'As you wish, oh great one)"
        )

        def on_line(ev: Any) -> None:
            msg = getattr(ev, "line", "") or ""
            if not msg:
                return
            if "critical" in msg:
                m = crit_re.match(msg)
                if m:
                    self._record_crit(m.group("n"), int(m.group("d")))
                    return
            m = pet_id.match(msg)
            if m:
                with self._lock:
                    self._pet_name = m.group("p")
                return
            m = self_ds.match(msg)
            if m:
                # Incoming damage shield: "You were hit by non-melee for N damage."
                self._record("", "You", int(m.group("d")), "non-melee")
                return
            if "healed" in msg:
                m = heal_out.match(msg)
                if m:
                    self._record("You", m.group("t"), int(m.group("d")), "heal")
                    return
                m = heal_in.match(msg)
                if m:
                    self._record(m.group("a"), "you", int(m.group("d")), "heal")
                    return
            if ", but " in msg:
                m = miss_out.match(msg)
                incoming = m is None
                if m is None:
                    m = miss_in.match(msg)
                if m:
                    w = avoid_word.search(m.group("rest"))
                    if w:
                        # actor-based: the defender's avoidance, their lane
                        word = {"parr": "parry"}.get(w.group(1).lower(), w.group(1).lower())
                        self._record_miss("out" if incoming else "in", word)
                    else:
                        self._record_miss("in" if incoming else "out", "miss")
                    return
            if " point" not in msg:
                return
            m = you_hit.match(msg)
            if m:
                self._record("You", m.group("t"), int(m.group("d")), "melee")
                return
            m = other_hit.match(msg)
            if m:
                self._record(m.group("a"), m.group("t"), int(m.group("d")), "melee")
                return
            m = non_melee.match(msg)
            if m:
                # Host convention: non-melee is attributed to you.
                self._record("You", m.group("t"), int(m.group("d")), "non-melee")

        ctx.subscribe(LineEvent, on_line)

    # --- classification (driver thread) ------------------------------------
    def _record(self, attacker: str, target: str, amount: int, dtype: str = "") -> None:
        if amount <= 0:
            return
        tgt = (target or "").strip().lower()
        atk = (attacker or "").strip().lower()
        dt = (dtype or "").strip().lower()
        nonmelee = dt == "non-melee"
        heal = dt == "heal"
        # Check incoming first: a non-melee line can carry both attacker "You"
        # and target "You"; the target wins.
        if tgt == "you":
            kind = "inheal" if heal else "inns" if nonmelee else "in"
        elif atk == "you":
            kind = "outheal" if heal else "outns" if nonmelee else "out"
        else:
            with self._lock:
                pet = self._pet_name.strip().lower()
            if pet and atk == pet:
                kind = "pet"
            else:
                return
        text = str(amount)
        with self._lock:
            if kind in ("out", "outns", "pet"):
                now = time.monotonic()
                for i, (crit_amount, ts) in enumerate(self._crits):
                    if crit_amount == amount and now - ts <= 1.5:
                        del self._crits[i]
                        text += "!"
                        break
            self._pending.append((kind, text, amount))

    def _record_crit(self, actor: str, amount: int) -> None:
        """Remember a crit announcement so the matching hit gets its '!'.

        Other players' crits are broadcast too, so only keep announcements
        from "You", the active character (``ctx.player.name`` — the same
        source as the host's Character tab), or the pet. When the host hasn't
        identified the character yet, accept everything rather than drop
        genuine crits.
        """
        who = (actor or "").strip().lower()
        player = getattr(self._ctx, "player", None)
        me = (getattr(player, "name", "") or "").strip().lower()
        with self._lock:
            pet = self._pet_name.strip().lower()
            if me and who not in ("you", me, pet):
                return
            self._crits.append((amount, time.monotonic()))

    def _record_miss(self, side: str, word: str) -> None:
        """Queue an avoidance tick ('miss'/'dodge'/…) into its own lane
        ("outmiss"/"inmiss"); the lane's enable toggle governs visibility."""
        with self._lock:
            self._pending.append((f"{side}miss", word, 0))

    # --- GUI thread reads --------------------------------------------------
    def drain(self) -> list[tuple[str, str, int]]:
        """Return and clear buffered hits. Called from the window's Qt timer."""
        with self._lock:
            items = list(self._pending)
            self._pending.clear()
        return items

    # --- settings (GUI thread only) ----------------------------------------
    def _load_settings(self, ctx: PluginContext) -> None:
        try:
            stored = ctx.storage.load() or {}
        except Exception as exc:  # noqa: BLE001 - storage is best-effort
            ctx.logger.warning("floating-combat-text: could not load settings: %s", exc)
            stored = {}
        self._first_run = not stored
        if isinstance(stored, dict):
            for key, value in stored.items():
                if key in self._settings:
                    self._settings[key] = value
            # Migration: setup_on_open used to default True; stores written
            # before auto_show existed carry that old default, not a choice.
            if "auto_show" not in stored:
                self._settings["setup_on_open"] = False
            # Migration: the single global "rise_pct" became per-lane dist_*.
            if "rise_pct" in stored and "dist_out" not in stored:
                try:
                    rise = int(stored["rise_pct"])
                except (TypeError, ValueError):
                    rise = 42
                for kind in (
                    "out", "outns", "pet", "in", "inns",
                    "outheal", "inheal", "outmiss", "inmiss",
                ):
                    self._settings[f"dist_{kind}"] = rise

    def settings(self) -> dict[str, Any]:
        """A copy for the settings-page builder."""
        return dict(self._settings)

    def get(self, key: str) -> Any:
        """Live read for the overlay; falls back to the default."""
        return self._settings.get(key, DEFAULTS.get(key))

    def first_run(self) -> bool:
        """True on a fresh install (no stored settings at activate)."""
        return self._first_run

    def apply_settings(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            if key in self._settings:
                self._settings[key] = value
        self._persist()

    def set_lane_position(self, kind: str, x: float, y: float, *, persist: bool = True) -> None:
        """Called live while a lane is dragged in the overlay's setup mode."""
        self._settings[f"x_{kind}"] = round(float(x), 4)
        self._settings[f"y_{kind}"] = round(float(y), 4)
        if persist:
            self._persist()

    def _persist(self) -> None:
        if self._ctx is None:
            return
        try:
            self._ctx.storage.save(self._settings)
        except Exception as exc:  # noqa: BLE001 - storage is best-effort
            self._ctx.logger.warning("floating-combat-text: could not save settings: %s", exc)

    def deactivate(self) -> None:
        self._persist()

    def open_overlay(self) -> bool:
        """Bring the overlay forward and into setup mode. Returns False if the
        window has not been created yet (open it from the tray menu first)."""
        win = self._window
        if win is None:
            return False
        win.enter_setup_and_show()
        return True

    def reset_defaults(self) -> None:
        """Restore every setting to its default and refresh the overlay."""
        self._settings = dict(DEFAULTS)
        self._persist()

    def request_test(self) -> bool:
        """Show the overlay and run the sample sequence: three waves, one
        number per lane, 0.6 s apart (scheduling lives in the window, which
        owns the Qt timers). Returns False if the window doesn't exist yet."""
        win = self._window
        if win is None:
            return False
        win.show()
        win.raise_()
        win.start_test()
        return True

    # --- presets / sharing --------------------------------------------------
    def preset_dir(self) -> Any:
        """Folder for saved layout presets, created on demand (or ``None``)."""
        storage = getattr(self._ctx, "storage", None)
        base = getattr(storage, "data_dir", None)
        if base is None:
            return None
        path = base / "presets"
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        return path

    def export_settings(self, path: str, extra: dict[str, Any] | None = None) -> str:
        """Write the full settings (with unapplied page edits layered on top)
        to ``path`` as JSON. Returns "" on success, else an error message."""
        data = dict(self._settings)
        if extra:
            for key, value in extra.items():
                if key in data:
                    data[key] = value
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except OSError as exc:
            return str(exc)
        return ""

    def import_settings(self, path: str) -> str:
        """Load a preset JSON and apply it (positions included). Returns ""
        on success, else an error message. Unknown keys are ignored, so a
        preset from a newer plugin version still loads."""
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            return str(exc)
        if not isinstance(data, dict):
            return "not a settings file (expected a JSON object)"
        known = {k: v for k, v in data.items() if k in self._settings}
        if not known:
            return "no recognised settings in that file"
        self.apply_settings(known)
        return ""

    # --- window / settings factories ---------------------------------------
    def _make_window(self, wctx: Any) -> Any:
        from .window import CombatTextWindow

        self._window = CombatTextWindow(wctx, self)
        return self._window

    def _build_settings_page(self, parent: Any) -> Any:
        from .window import build_settings_page

        return build_settings_page(parent, self.settings(), self)

    def _apply_settings_page(self, page: Any) -> None:
        from .window import read_settings_page

        self.apply_settings(read_settings_page(page))


def create_plugin() -> CombatTextPlugin:
    return CombatTextPlugin()
