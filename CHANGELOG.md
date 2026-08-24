# Changelog

## 1.10.0
- The overlay opens automatically when nParse+ starts (no tray visit needed;
  opt out in settings), and the setup guides now appear only on a fresh
  install instead of every launch.
- Miss/avoidance ticks in two new draggable lanes ("Your misses / avoids" and
  "Enemy misses / avoids", off by default) — actor-based, so your riposte
  shows on your side and the mob's on theirs.
- Real crit detection: a hit announced by "scores a critical hit!" /
  "delivers a critical blast!" renders with a trailing "!" (e.g. 49!). Crit
  lines are filtered to you, your character's name, and your pet, so nearby
  players' crits can't mislabel your hits.
- Per-lane travel distance ("Travel %" column) replaces the global slider —
  heals can fall far while hits pop short. Existing saved value migrates.
- Layout presets: Save preset… / Load preset… buttons write and apply full
  setups (positions included) as JSON files you can keep or share.
- Setup mode gains a clickable "hide guides" button (the double-click was
  eaten by window-dragging on the first click).

## 1.9.2
- Release pipeline: reproducible zip builds and correct registry publish
  fields. No changes to the plugin itself.

## 1.9.1
- Fix a crash on load (wrong Qt attribute name for click-through).

## 1.9.0
- Spawn "pop" animation, click-through when locked, Reset-to-defaults and Test
  buttons, and overlay labels matched to the non-melee naming.

## 1.8.x
- Per-lane 8-way travel direction; drag-only positioning that persists.

## 1.6.0
- Outgoing and incoming healing lanes.

## 1.5.0
- Non-melee / damage-shield lanes (outgoing and incoming).

## 1.0.0
- Initial release: floating damage numbers for your hits, pet, and incoming,
  with a big-hit glow and a full settings page.
