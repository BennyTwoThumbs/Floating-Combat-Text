# Floating Combat Text — user guide

MMO-style floating numbers for nParse+. Your hits, your pet, incoming damage,
damage shields / non-melee, and healing pop up as colour-coded numbers that
drift and fade. It only reads your EQ log — nothing is sent anywhere.

## Install

1. In nParse+: tray icon → **Open Plugins Folder**.
2. Copy the `combat_text` folder into it.
3. Settings → **Advanced** → tick **Enable plugins**, then restart nParse+.
4. **Approve** "Floating Combat Text" when prompted.
5. Open it from the **tray menu** (same list as Maps, DPS Meter, etc.).

## First run — line it up

It opens in **setup mode**: you'll see a faint border, a blue centre line, and
a labelled ring for every lane.

1. Drag the window (empty space) so the **centre line** sits on your character.
2. Drag each **lane's ring** to where you want its numbers to appear — they
   save automatically the moment you let go.
3. **Double-click** the overlay to hide the guides. You're done.

To move things again later: open the settings page (below) and click
**Open overlay in setup mode**.

## The settings page

nParse+ Settings → **Floating Combat Text**:

- **Open overlay in setup mode / Test / Reset to defaults** — buttons up top.
  *Test* fires sample numbers so you can preview without fighting.
- **Lanes** — for each lane: on/off, colour, size, and **Move** (which of 8
  directions the numbers drift).
- **Big hits** — hits at/above the threshold get a coloured glow and a size
  bump.
- **Motion and feel** — travel distance, lifetime, spread, pop-in animation,
  and **click-through** (see below).

Positions aren't on this page — you set those by dragging in setup mode.

## The lanes

| Lane | Shows |
|------|-------|
| Your hits | your melee |
| Your non-melee | your damage shield / nukes / procs |
| Pet | your pet's hits |
| Incoming | melee damage taken |
| Incoming non-melee | a mob's damage shield / nukes on you |
| Outgoing healing | heals you cast |
| Incoming healing | heals cast on you |

## Quick controls

- **Drag empty space** → move the whole overlay.
- **Drag a lane ring** (setup mode) → move just that lane.
- **Double-click** → show/hide the setup guides.
- **Test button** → preview numbers anytime.

## Good to know

- **Click-through is on by default:** once you leave setup mode, clicks pass
  straight through the overlay to the game, so it never blocks you. Because of
  that, double-click won't re-open setup while it's locked — use the
  **Open overlay in setup mode** button. (You can turn click-through off in
  Motion and feel if you'd rather double-click toggle it.)
- **"Your non-melee" includes your nukes**, not just your damage shield — the
  game logs them the same way, so they can't be separated.
- Pet numbers start once your **pet has spoken** to you this session (summon,
  `/pet attack`, `/pet follow`, …).
- Everything is per-lane, so turn off any lane you don't care about.

## Updating

If you installed from a registry (Settings → Plugins → Browse registry), an
**Update** button appears on the row when a new version is out. Otherwise,
replace the `combat_text` folder with the newer one and restart.
