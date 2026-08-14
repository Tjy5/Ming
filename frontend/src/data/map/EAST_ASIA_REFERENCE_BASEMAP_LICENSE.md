# Natural Earth reference basemap provenance

The generated `eastAsiaReferenceBasemap.ts` uses the Natural Earth 1:50m land
dataset from the pinned `nvkelso/natural-earth-vector` commit
`ca96624a56bd078437bca8184e78163e5039ad19`.

Natural Earth states that all versions of Natural Earth raster and vector map
data are in the public domain. No permission is needed to use the data, and
credit is not required. This project records the source anyway so the geometry
can be reproduced and audited.

- Natural Earth terms: https://www.naturalearthdata.com/about/terms-of-use/
- Source file: https://raw.githubusercontent.com/nvkelso/natural-earth-vector/ca96624a56bd078437bca8184e78163e5039ad19/geojson/ne_50m_land.geojson
- SHA-256: `e874b27a51d146452be360cafb3cc50c86001074a67d534113e6534682f9826b`

The project conversion clips the public-domain source to `65-157 E`, `7-57 N`
and projects it into the fixed `0 0 1200 650` SVG viewBox at a uniform `13`
SVG units per degree on both axes. Historical polity labels and the eight
strategic gameplay overlays are project-authored data and are not part of
Natural Earth.
