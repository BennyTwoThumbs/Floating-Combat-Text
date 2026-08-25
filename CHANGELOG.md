# Changelog

## 1.12.2
- Fix: other players' damage could land in the pet lane. EQ's Complete Heal
  message ("<name> beams a smile at <target>") is classified by the host as a
  pet lifetap, so a cleric chain-healing in your group was being adopted as
  your pet. Pet names are now taken only from lines that identify your own pet,
  a directed "tells you, 'Attacking … Master.'" wins over broadcast lines, and
  the pet is forgotten when it dies or is reclaimed.

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
