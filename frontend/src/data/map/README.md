# China reference basemap and Yuanming strategic overlay

## Modern reference geometry

`chinaReferenceBasemap.ts` is generated from `@svg-maps/china@2.0.0` and is
used only as a subdued, non-interactive modern geographic reference. It does
not describe Yuan or Ming administrative boundaries and has no 1368 temporal
meaning.

- Source package: `@svg-maps/china`
- Package version: `2.0.0`
- Author: Victor Cazanave
- Package URL: https://www.npmjs.com/package/@svg-maps/china/v/2.0.0
- Source repository: https://github.com/VictorCazanave/svg-maps/tree/master/packages/china
- Tarball URL: https://registry.npmjs.org/@svg-maps/china/-/china-2.0.0.tgz
- npm SHA-1: `853b3c7eba2762637fcde433decc9611d32f3325`
- npm integrity: `sha512-/B0a4hYJHRtfcUG+x6BudQFWhLQyPoaN2WbqfdEeWeXnwef6oXaE93Msrq2odu72c09vE+G4Ds9+n60Qsr4p1g==`
- Download SHA-256: `c294cb2f3478423d6add28fcec0e185a82cc3d866746e28a524ac5b9214f5e05`
- License: Creative Commons Attribution 4.0 International (`CC-BY-4.0`)
- Attribution: Map of China by Victor Cazanave, from `@svg-maps/china@2.0.0`, licensed under CC-BY-4.0
- License copy: `CHINA_REFERENCE_BASEMAP_LICENSE.md`
- Conversion date: `2026-08-13`
- Original viewBox: `0 0 774 569`
- Target viewBox: `0 0 774 569` (identity transform)
- Simplification: none; source path strings are preserved exactly
- Conversion: `node scripts/vendor-china-reference-map.mjs`

The conversion script downloads the fixed tarball, verifies npm SHA-512,
npm SHA-1, and SHA-256 before reading any geometry, and then extracts only the
stable province `id`, English `name`, and SVG `path`. The generated registry is
committed so the application has no runtime package, tile, image, font, or
network dependency.

## Yuanming strategic overlay

`geography.ts` owns `YUANMING_STRATEGIC_OVERLAY`, an explicit eight-entry
gameplay registry for `dadu`, `lianghuai`, `wuchang`, `taiping`, `yingtian`,
`zhenjiang`, `pingjiang`, and `hangzhou`. Each entry has its own stable ID,
legacy aliases, approximate coverage path, geographic anchor, and label
viewport. These project-authored shapes are approximate strategic interaction
areas based on the Yuan-end campaign setting. They are not derived from modern
province order or names and do not claim exact historical administrative
boundaries.

`joinRegionsToMap` remains the only adapter from mutable API `Region` records
to these stable overlay IDs. Unknown, duplicate, and missing region states are
reported rather than guessed.
