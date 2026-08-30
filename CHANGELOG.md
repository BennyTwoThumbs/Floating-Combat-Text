# Changelog

## 1.15.0
- The direction spread is now per-lane. A new **Spread** checkbox next to each
  lane's Grav box turns the cone on or off for that lane, so numbers can fan
  out in one lane and travel dead straight in another. It is on for every lane
  by default, matching the old behaviour; the "Direction spread (°)" slider is
  still the shared angle for the lanes that have it ticked.

## 1.14.0
- The floating numbers can now use any installed font. New **Font** dropdown
  and **Bold** toggle in the settings page apply to the numbers and their
  labels. The default keeps the app font, so existing overlays look the same. A
  font you pick has to be installed on any machine that loads the overlay, or
  it falls back to the default.

## 1.13.4
- Fix the Ding! level-up flourish never firing: its detection regex was
  missing the backslashes on `\s*` and `\d+` (written as bare `s*` and `d+`),
  which cannot match real whitespace or digits — so the flourish was
  effectively dead on every real level-up, in both the typed-event path and
  the raw-line fallback.

## 1.13.3
- Fix click-through on Linux: a locked overlay stayed invisible but still
  swallowed clicks. Click-through was using WA_TransparentForMouseEvents,
  which is aimed at child widgets — a top-level window needs the
  Qt.WindowTransparentForInput flag for X11 and Wayland to clear its input
  region. Both are now set, and the window is re-shown so the change lands.

## 1.13.2
- Setup mode is much easier to aim at: the window border is drawn thick and
  bright (it is what you grab to resize), a dashed inner line now shows how
  far the resize band reaches, and the lane rings, direction ticks and centre
  guide are all thicker.
- Lane rings can no longer be dragged under the resize band, where the edge
  would win every press and the ring could never be picked up again.

## 1.13.1
- The settings page's "Open overlay in setup mode" button is now a toggle:
  **Setup mode** / **Leave setup mode**, relabelling itself to match the
  overlay's current state. It still shows the overlay if it was hidden.

## 1.13.0
- Numbers now fan out in a cone around their lane's direction instead of all
  travelling the identical vector, and each one's travel distance varies a
  little. New "Direction spread (°)" setting — 0 restores the old parallel
  look. (Thanks to the user who pointed out it read too uniform.)
- "Size by damage" is now a choice rather than a checkbox, with a new
  **Relative to your typical hit** mode: a hit is sized against the median of
  recent hits in the same lane, so a big hit reads big at level 10 and at 60,
  and pet numbers are judged against other pet numbers. The old fixed curve is
  still there as "By raw damage", and "All the same size" turns sizing off.
  Existing installs with scaling on are migrated to the relative mode.
- Fountain motion: a per-lane "Grav" tick makes gravity bend that lane's
  numbers downward as they travel, turning the straight drift into an arc —
  tossed up, over the top, and away. The strength is one "Gravity (%)" setting
  under Motion. Off everywhere by default, so nothing moves differently until
  you ask. Point a lane up, widen the spread, tick Grav, try about 120.
- The big-hit flourish is now graduated instead of on/off: hits are graded
  into three tiers and the glow thickens and brightens with each, so a good
  hit gets a thin halo and a monster gets a fat one. In relative mode the
  tiers grade against your own recent hits (1.6x, 2.6x, 4x the median), so
  they keep meaning something as you level; otherwise they step off multiples
  of the big-hit threshold. Heals are never graded.
- "Ding!" flourish on level up: when the log says you have gained a level, a
  big gold "Ding! N!" blooms out of the centre of the overlay and fades, with
  a scatter of small ones thrown in every direction. It has no lane and no
  ring — it borrows the whole overlay for about a second and a half. On by
  default with its own colour, and deliberately not in the Test preview — it
  should be a surprise when it happens.
- Numbers now fade out as they approach the overlay edge instead of being
  clipped mid-glyph — which gravity made routine, since numbers fall past the
  bottom of the box.
- Fix: setup mode could draw its rings while the overlay stayed deaf to the
  mouse, so neither lanes nor the resize edges could be clicked. Click-through
  becomes a native window style that Windows only reads when the window is
  created, so toggling it on an already-visible overlay did nothing; the
  window is now rebuilt in place (geometry preserved) when it changes.
- The window's resize edges work again in setup mode: a band along each edge
  is reserved for resizing, so the lane grab zones no longer swallow it.
- The Test button now escalates every lane and primes the relative baseline,
  so a test actually demonstrates the sizing instead of falling back to the
  raw-damage curve.

## 1.12.2
- Fix: other players' damage (and their pets') could land in your pet lane.
  The host reports a pet event for broadcast chatter — "At your service
  Master", "Following you, Master", "My leader is X", and EQ's Complete Heal
  line "<name> beams a smile at <target>" — all of which a nearby player's pet
  or cleric emits too, so whoever spoke last got adopted as your pet.
  Your pet is now named only by lines that prove it is yours: a directed
  "tells you, 'Attacking … Master.'" (/pet attack) or "My leader is <you>"
  (/pet leader), and it is forgotten when the pet dies or is reclaimed.
  Adoptions are logged to nparseplus.log if you ever need to check.

## 1.12.1
- Releases now also attach a versionless `floating-combat-text.zip`, so
  `releases/latest/download/floating-combat-text.zip` is a permanent link to
  the newest build. README gains a live version badge. No plugin changes.

## 1.12.0
- Killing-blow flourish: the hit that kills flares bright and lingers about
  twice as long, with an optional "Killing blow" label (uses your label size).
  Fires only on your own kills and your pet's — nothing fires when something
  else dies nearby. Both parts toggleable, on by default.

## 1.11.0
- Special-attack labels: backstabs, bashes, kicks and Crippling Blows draw
  their name above the number (`backstab 250`, `Crippling Blow 96!`). Normal
  swings stay bare. Crippling Blows are name-filtered like crits, so nearby
  players can't trigger yours.
- New settings: "Label special attacks" (on by default — untick for
  numbers-only) and an independent "Label size (px)".

## 1.10.1
- Setup mode: lane grab zones are much more forgiving (~36 px beyond the ring,
  label included; nearest ring wins), so near-misses no longer drag the whole
  window.
- The Test button now plays three staggered waves (0.6 s apart, one number per
  lane) instead of dumping everything in one frame — wave two shows a crit.

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
