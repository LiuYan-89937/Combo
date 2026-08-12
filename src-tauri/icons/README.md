# Application Icons

Application icons are generated from the Combo brand source by
`scripts/generate_icons.py`. The generated artwork uses a pure-white rounded
tile with a transparent safety margin so Windows and older macOS releases do
not render it as a hard-edged square.

- `32x32.png` - 32x32 PNG icon
- `128x128.png` - 128x128 PNG icon
- `128x128@2x.png` - 256x256 PNG icon (retina)
- `icon.icns` - macOS icon bundle
- `icon.ico` - Windows icon

Regenerate all platform assets with:

```bash
python3 scripts/generate_icons.py
```
