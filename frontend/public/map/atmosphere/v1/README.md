# Original Map Atmosphere Assets v1

These files are original AI-generated decorative textures for the Ming desktop map. They load locally and sit below the repository-owned reference basemap and all authoritative gameplay overlays. They do not define geography, state, labels, routes, coordinates, or hit areas. The solid SVG `map-water` rectangle remains the code-native fallback when an image is unavailable.

Generation used the installed ImageGen fallback CLI at `C:/Users/TJY5/.codex/skills/.system/imagegen/scripts/image_gen.py`. No input image was supplied: no reference-game material, screenshot, map, icon, historical image, or unlicensed source was used. The generated files contain no embedded third-party asset and are intended only as low-opacity decorative surfaces in this project.

## `paper-water-wash-v1.webp`

- SHA-256: `26380d37279f91050a035d151333fb7b0529c991b678dabb40cd6b1350a57615`
- Generated: 2026-08-13
- Use case: `stylized-concept`
- Runtime purpose: quiet rice-paper and pale water-wash substrate
- Tool/mode: installed `scripts/image_gen.py`, explicitly authorized CLI/API fallback, `generate`
- Model/request parameters: `gpt-image-2`, `quality=high`, requested `size=2048x2048`, `output_format=png`, `n=1`
- Delivered master: `1254x1254` RGB PNG, SHA-256 `f52a2f37189f3c60c7eea46b06157eb99376b06830626d2487e1f94d7f98cd32`, retained in task-local research evidence
- Input images and roles: none
- Selection: low-quality draft passed checks for text/watermarks, map-like geometry, focal hotspots, edge vignette, and period mismatch; the unchanged prompt was promoted to high quality
- Post-processing: Pillow 12.1.1; RGB conversion; Lanczos downscale to `1024x1024`; WebP quality 82, method 6; no crop, retouch, compositing, or added content
- Limitations: decorative only; must not be interpreted as water boundaries, coastlines, weather state, or location data

Prompt:

```text
Use case: stylized-concept
Asset type: decorative historical strategy-map substrate
Primary request: Create a seamless-looking square field of softly aged Chinese rice paper merging into a restrained pale ink-and-mineral water wash. It will be used at very low opacity beneath an authoritative vector map in a desktop historical strategy game.
Scene/backdrop: edge-to-edge abstract paper and calm water texture, no horizon and no distinct place.
Style/medium: understated traditional ink wash and natural paper fibers, historically plausible materials, matte and hand-made rather than digital or photographic.
Composition/framing: uniform top-down texture, balanced detail across the full frame, no focal point, no large isolated marks, usable when cropped or scaled.
Lighting/mood: diffuse daylight, quiet and sober.
Color palette: pale rice paper, cool gray-green water, faint muted teal, restrained warm fiber; low contrast.
Materials/textures: fine mulberry-paper fibers, subtle tide blooms, sparse ink granulation.
Constraints: purely decorative and non-geographic; no landmass, coastline, boundary, route, compass, grid, label, icon, settlement, building, person, animal, vehicle, weapon, flag, seal, text, calligraphy, number, logo, trademark, or watermark; no modern object; no bright highlight; no dark vignette; no obvious repeating tile seam.
Avoid: maps, cartography, recognizable terrain, dramatic waves, photorealistic landscape, legible marks, central subject, high contrast.
```

## `terrain-drybrush-v1.webp`

- SHA-256: `7f02b84b8636520d5884a0d32467b4fd32a6823df82e4317e6717edb6ffe24df`
- Generated: 2026-08-13
- Use case: `stylized-concept`
- Runtime purpose: subdued dry-brush relief and mineral-earth atmosphere
- Tool/mode: installed `scripts/image_gen.py`, explicitly authorized CLI/API fallback, `generate`
- Model/request parameters: `gpt-image-2`, `quality=high`, requested `size=2048x2048`, `output_format=png`, `n=1`
- Delivered master: `1254x1254` RGB PNG, SHA-256 `c302249da5f27ea38b154f1bbd07805a60cc6b4dc81bf1ec1078313c6d2ec4b4`, retained in task-local research evidence
- Input images and roles: none
- Selection: low-quality draft passed checks for text/watermarks, map-like geometry, focal hotspots, edge vignette, and period mismatch; its grain, saturation, and lighting matched the companion asset, so the unchanged prompt was promoted
- Post-processing: Pillow 12.1.1; RGB conversion; Lanczos downscale to `1024x1024`; WebP quality 82, method 6; no crop, retouch, compositing, or added content
- Limitations: decorative only; must not be interpreted as relief, mountains, roads, strategic routes, weather state, or location data

Prompt:

```text
Use case: stylized-concept
Asset type: decorative historical strategy-map terrain wash
Primary request: Create a seamless-looking square, non-geographic dry-brush terrain atmosphere texture for very low-opacity use beneath an authoritative vector map in a desktop Yuan-end historical strategy game.
Scene/backdrop: abstract traces of distant mountain relief, eroded earth, mist, and dry brush on aged rice paper; no identifiable landscape and no horizon.
Style/medium: restrained Chinese ink wash with mineral-earth pigment, same matte paper character as a pale gray-green water-wash companion asset.
Composition/framing: uniform top-down field, small and medium organic texture distributed evenly, broad negative space, no focal peak, no directional route, usable when cropped or scaled.
Lighting/mood: diffuse, weathered, sober, archival.
Color palette: diluted charcoal, muted moss gray, pale ochre, warm rice-paper undertone; low saturation and low contrast.
Materials/textures: dry-brush grain, faint washed relief, paper fibers, soft mist blooms.
Constraints: purely decorative and non-geographic; no China outline, landmass, coastline, province or historical boundary, river path, road, route, compass, grid, label, icon, settlement, building, person, animal, vehicle, weapon, flag, seal, text, calligraphy, number, logo, trademark, or watermark; no modern object; no bright highlight; no dark vignette; no obvious repeating tile seam.
Avoid: literal map, recognizable mountains or named terrain, sharp ridgelines, dramatic scenery, photorealism, legible marks, central subject, high contrast.
```

