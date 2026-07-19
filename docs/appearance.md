# Appearance

Pies Pear Music ships ten curated presets: Amber Night, Midnight Blue, OLED,
Lavender, Daylight, High Contrast, Forest, Rosewood, Solarized, and Paper. Select a preset in **Settings →
Appearance**. The choice is stored only in the desktop webview's local storage
and never changes operational configuration, music, logs, or credentials.

## Portable preset selection

The settings page can export and import a small JSON file containing the
selected preset. Version 0.1 supports this schema only:

```json
{
  "version": 1,
  "theme": "midnight"
}
```

Unknown versions and preset names are rejected. Arbitrary CSS or JavaScript is
never imported. Use **Reset** to restore Amber Night.

Settings displays the calculated contrast ratio between the preset's primary
text and canvas colors and flags ratios below the WCAG AA 4.5:1 target.

The six preset IDs are `amber-night`, `midnight`, `oled`, `lavender`,
`daylight`, and `high-contrast`.
