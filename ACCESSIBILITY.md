# Accessibility

OMGA is a terminal user interface. We aim to keep it usable with keyboard-only
navigation, clear contrast themes, and optional ASCII fallbacks.

## Supported environments

- Terminals with UTF-8 (or `OMGA_UNICODE=0` for ASCII glyphs)
- Screen readers that consume terminal text streams (results vary by emulator)
- Keyboard-first workflows — every primary action has a shortcut or `/command`

## Known limitations

- Mouse reporting is off by default so drag-to-copy works; set `OMGA_MOUSE=1`
  to enable wheel scrolling in overlays.
- Some Braille / NVDA setups may not announce streaming token updates live.
- Color themes assume a dark-capable terminal; use `/theme` to pick alternatives.

## Reporting barriers

If you hit an accessibility barrier, open an issue with the
`accessibility` label or contact [pouriahosseini.ir](https://pouriahosseini.ir).
Describe your environment (OS, terminal, assistive tech) and what blocked you.
