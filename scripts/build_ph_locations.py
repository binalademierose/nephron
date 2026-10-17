"""
build_ph_locations.py - builds Nephron's two location files from the official Philippine boundaries.

  data/ph_locations.json     every province (for "Which province do you live in?") and, for Pangasinan, every
                             municipality/city and barangay - names and PSGC codes
  data/maps/pangasinan.json  ready-to-draw SVG outlines of Pangasinan's municipalities/cities and barangays, for the
                             administrator's heatmap (drawn on the server: no map service, no API key, no internet)

Source: faeldon/philippines-json-maps (MIT licence), 2023 folder, built from the PSA's Philippine Standard
Geographic Code (PSGC) boundaries as of 31 December 2023. Codes are PSGC codes, so an LGU can match them to its own
records. Run it again only to update the boundaries:

    git clone --depth 1 https://github.com/faeldon/philippines-json-maps.git
    python scripts/build_ph_locations.py path/to/philippines-json-maps
"""
import glob
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANGASINAN = "105500000"
MAP_WIDTH = 1000.0
NCR_REGION = "1300000000"


def _rings(geometry):
    if not geometry:                                             # a few barangays have no outline in the source data
        return []
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiPolygon":
        return geometry["coordinates"]
    return []


def _clean_province(props):
    name, code = props.get("adm2_en"), str(props["adm2_psgc"])
    if not name:
        return "Special Geographic Area (BARMM)", code
    return name.replace(" (Not a Province)", "").replace("City of Isabela", "City of Isabela (Basilan)"), code


def provinces(repo):
    found, ncr = [], False
    for path in glob.glob(os.path.join(repo, "2023/geojson/regions/lowres/*.json")):
        for feature in json.load(open(path, encoding="utf-8"))["features"]:
            props = feature["properties"]
            if str(props["adm1_psgc"]) == NCR_REGION:
                ncr = True                       # Metro Manila's four districts are asked as one choice
                continue
            name, code = _clean_province(props)
            found.append({"code": code, "name": name})
    if ncr:
        found.append({"code": NCR_REGION, "name": "Metro Manila (NCR)"})
    return sorted(found, key=lambda p: p["name"])


def _projector(features):
    features = [f for f in features if f.get("geometry")]
    lons = [pt[0] for f in features for poly in _rings(f["geometry"]) for ring in poly for pt in ring]
    lats = [pt[1] for f in features for poly in _rings(f["geometry"]) for ring in poly for pt in ring]
    min_lon, max_lon, min_lat, max_lat = min(lons), max(lons), min(lats), max(lats)
    k = math.cos(math.radians((min_lat + max_lat) / 2))          # equirectangular, true to scale at Pangasinan's latitude
    scale = MAP_WIDTH / ((max_lon - min_lon) * k)
    height = (max_lat - min_lat) * scale

    def project(pt):
        return round((pt[0] - min_lon) * k * scale, 1), round((max_lat - pt[1]) * scale, 1)
    return project, round(height, 1)


def _path_and_centre(geometry, project):
    parts, best = [], (0.0, None)
    for poly in _rings(geometry):
        for index, ring in enumerate(poly):
            points = []
            for pt in ring:
                p = project(pt)
                if not points or p != points[-1]:
                    points.append(p)
            if len(points) < 3:
                continue
            parts.append("M" + "L".join(f"{x:g},{y:g}" for x, y in points) + "Z")
            if index == 0:                                       # the outer ring: label the largest piece
                area = 0.0
                cx = cy = 0.0
                for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
                    cross = x1 * y2 - x2 * y1
                    area += cross
                    cx += (x1 + x2) * cross
                    cy += (y1 + y2) * cross
                if abs(area) > abs(best[0]):
                    best = (area, (round(cx / (3 * area), 1), round(cy / (3 * area), 1)) if area else points[0])
    return "".join(parts), best[1]


def main(repo):
    province_file = os.path.join(repo, f"2023/geojson/provdists/medres/municities-provdist-{PANGASINAN}.0.01.json")
    towns = json.load(open(province_file, encoding="utf-8"))["features"]
    barangay_features = []
    for path in sorted(glob.glob(os.path.join(repo, f"2023/geojson/municities/medres/bgysubmuns-municity-{PANGASINAN[:4]}*.json"))):
        barangay_features += json.load(open(path, encoding="utf-8"))["features"]
    project, height = _projector(towns)

    municipalities, map_towns = [], []
    for feature in sorted(towns, key=lambda f: f["properties"]["adm3_en"]):
        props = feature["properties"]
        code, name, kind = str(props["adm3_psgc"]), props["adm3_en"], "City" if props["geo_level"] == "City" else "Municipality"
        municipalities.append({"code": code, "name": name, "kind": kind})
        path, centre = _path_and_centre(feature["geometry"], project)
        map_towns.append({"code": code, "name": name, "path": path, "cx": centre[0], "cy": centre[1]})

    barangays, map_barangays = {}, []
    for feature in sorted(barangay_features, key=lambda f: (f["properties"]["adm3_psgc"], f["properties"]["adm4_en"])):
        props = feature["properties"]
        town, code, name = str(props["adm3_psgc"]), str(props["adm4_psgc"]), props["adm4_en"]
        barangays.setdefault(town, []).append({"code": code, "name": name})
        path, centre = _path_and_centre(feature["geometry"], project)
        map_barangays.append({"code": code, "town": town, "name": name, "path": path, "cx": centre[0] if centre else None, "cy": centre[1] if centre else None})

    source = ("Philippine Standard Geographic Code (PSGC) boundaries as of 31 December 2023, via "
              "faeldon/philippines-json-maps (MIT licence)")
    locations = {"source": source, "provinces": provinces(repo),
                 "pangasinan": {"code": PANGASINAN, "name": "Pangasinan", "municipalities": municipalities, "barangays": barangays}}
    os.makedirs(os.path.join(ROOT, "data", "maps"), exist_ok=True)
    with open(os.path.join(ROOT, "data", "ph_locations.json"), "w", encoding="utf-8") as handle:
        json.dump(locations, handle, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(ROOT, "data", "maps", "pangasinan.json"), "w", encoding="utf-8") as handle:
        json.dump({"source": source, "width": MAP_WIDTH, "height": height, "municipalities": map_towns, "barangays": map_barangays},
                  handle, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(locations['provinces'])} provinces, {len(municipalities)} Pangasinan municipalities/cities, "
          f"{sum(len(v) for v in barangays.values())} barangays")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
