# East Asia basemap and mid-14th-century administrative governance

## Physical reference geometry

`eastAsiaReferenceBasemap.ts` is generated from Natural Earth 1:50m land
geometry. It provides coastlines, islands, and inland-water holes for the East
Asia context map. It contains no modern national or provincial boundaries and
does not claim to reconstruct exact 14th-century borders.

- Source repository: `nvkelso/natural-earth-vector`
- Source commit: `ca96624a56bd078437bca8184e78163e5039ad19`
- Source file: `geojson/ne_50m_land.geojson`
- Source URL: https://raw.githubusercontent.com/nvkelso/natural-earth-vector/ca96624a56bd078437bca8184e78163e5039ad19/geojson/ne_50m_land.geojson
- Download SHA-256: `e874b27a51d146452be360cafb3cc50c86001074a67d534113e6534682f9826b`
- Source scale: Natural Earth `1:50m`
- License: public domain
- License and provenance note: `EAST_ASIA_REFERENCE_BASEMAP_LICENSE.md`
- Conversion date: `2026-08-14`
- Geographic crop: `65-157 E`, `7-57 N`
- Target viewBox: `0 0 1200 650`
- Projection: Plate Carree/equirectangular at a uniform `13` SVG units per
  degree on both axes, with `2` SVG units of horizontal padding. Longitude and
  latitude are never independently stretched to fill the viewBox.
- Clipping: Sutherland-Hodgman rectangle clipping
- Simplification: none; projected coordinates are rounded to 0.01 SVG units
- Source features: `1420`; retained East Asia land features: `194`
- Conversion: `node scripts/vendor-east-asia-reference-map.mjs`

The conversion script downloads the pinned GeoJSON, verifies its SHA-256 and
feature count, clips it to the declared bounds, and writes fixed SVG paths. The
generated registry is committed so the application has no runtime tile,
network, font, or map-package dependency.

## Political paint grid

`eastAsiaPoliticalGrid.ts` is generated from Natural Earth and uses the same
crop, projection, and `1200 x 650` viewBox as the physical basemap. It contains
current country outlines and current China province outlines. These features
are never labeled with modern names in the UI; they are paint units for a
clearer historical map, not claims that current borders existed in the 1350s.

- Country source: `geojson/ne_50m_admin_0_countries.geojson`
- Country SHA-256: `3e458fc036ad0a66411f2c1e6cac49c5d7bfb81cb1123bc513b22511a2b7fdeb`
- Country source features: `242`; retained East Asia units: `33`
- Province source: `geojson/ne_50m_admin_1_states_provinces.geojson`
- Province SHA-256: `69a0e06e640b2d505858ae1cb63034e4677f3000b35a98e16312932b98c426b9`
- Province source features: `294`; retained China units: `31`
- Source commit and license: same pinned Natural Earth commit above, public domain
- Simplification: `0.65` viewBox units; output coordinates rounded to `0.1`
- Conversion: `node scripts/vendor-east-asia-political-grid.mjs`

The conversion script verifies both downloads before generating repository-owned
paths. The application has no runtime map, tile, or network dependency.

## Mid-14th-century paint groups

`geography.ts` owns three related registries:

- `HISTORICAL_POLITY_PAINT_GROUPS` maps country/province paint-unit IDs to
  surrounding polity colors and period labels.
- `YUAN_END_POLITY_LABELS` is a label-only projection of that registry, so names
  and IDs remain single-sourced.
- `YUAN_ADMINISTRATIVE_DIVISIONS` groups province paint units into the Yuan-era
  中书省、行省 and 宣政院 framework. Modern province names never render.
- `outlineLabelLayout.ts` parses the generated country/province SVG paths and
  fits each historical label inside its assigned outline. The authored label
  coordinates are preferences only; rendered coordinates are geometry-derived
  and avoid other historical labels where the outline has enough room.

`吐蕃诸部` is a low-prominence local historical-context label. It is rendered
smaller and lighter than the administrative label `宣政院辖地`; it does not
represent a second peer administrative division or a separate governance
target on the same outline.

The grouping is an orientation snapshot around the 1350s, not an authoritative
territorial claim or a year-by-year control map. Where a historical division
crossed a current province line, the whole current paint unit is assigned to one
group for legibility. Contested control remains represented only by the
interactive gameplay layer.

## Administrative governance compatibility

The historical administrative outlines are the map's visible and interactive
governance units. `LEGACY_REGION_BINDINGS` preserves the eight mutable scenario
records used by saves, events, and settlement, while assigning them to four
historical divisions:

- `中书省` -> `大都`
- `河南江北行省` -> `两淮`, `应天`, `太平`, `镇江`, `平江`
- `湖广行省` -> `武昌`
- `江浙行省` -> `杭州`

`joinRegionsToGovernanceDivisions` is the adapter from API `Region` records to
the twelve historical outlines. It averages rate/level fields, sums garrison
and collected tax, keeps the worst control state, and reports unknown,
duplicate, partial, and missing inputs without inventing values. The eight
divisions without current scenario records stay visible as hatched,
non-interactive outlines.

Backend decree settlement accepts both historical division targets and legacy
region targets. A historical division target expands to all bound legacy
regions before structured relief or validated free-form effects are applied;
legacy target names remain accepted for old saves and event content.
