# EnCap Liquid Glass icon recipe

These six 1024 × 1024 SVGs are ordered back-to-front for Apple
Icon Composer. They intentionally contain no outer rounded-square mask, baked
shadow, blur, translucency, or specular highlight; macOS supplies the enclosure
and Icon Composer supplies the material treatment.

## Import order

1. `00-background.svg`
2. `01-source-nodes.svg`
3. `02-assembly-flow.svg`
4. `02-capsule.svg`
5. `03-waveform.svg`
6. `04-chapter-markers.svg`

## Suggested Icon Composer settings

- Platforms: iOS and macOS; watchOS off unless a watch app is added later.
- Background fill: vertical gradient from `#172C94` to `#071B65`.
- Source nodes and assembly flow: combined group, Liquid Glass effects on,
  subtle translucency and refraction, restrained shadow.
- Waveform: combined group, low translucency, specular highlight on.
- Chapter markers: combined group, low translucency, specular highlight on,
  minimal shadow.
- Default appearance: an ice/silver-blue light background with the cyan,
  indigo, and coral identity colors preserved.
- Dark appearance: an explicit deep-blue gradient specialization that preserves
  cyan/coral contrast rather than relying on automatic recoloring.
- Mono appearance: verify clear and tinted previews inside Icon Composer.
- Do not add or import an enclosure shape. Preview macOS at small sizes before
  saving `AppIcon.icon`.

The completed `AppIcon.icon` is compiled by `script/build_and_run.sh` with
Xcode 26's asset catalog compiler. The build copies `Assets.car` into the app
for current, appearance-aware macOS releases. It also exports the Default
rendition and builds a complete 16–1024 px `AppIcon.icns` as the light/static
fallback for legacy macOS releases.
