"""Download surveyed superstructures and georeferenced SWISSIMAGE training chips.

The target is surveyed superstructure footprint, not exhaustive roof occupancy.
Split 512 m geographic blocks before rasterisation; leave 64 m at block edges
and remove EGIDs crossing splits. Current imagery may differ from survey dates.
"""
import argparse
import asyncio
import hashlib
import io
import json
from collections import Counter, defaultdict
from pathlib import Path

import httpx
import numpy as np
from PIL import Image
from shapely.geometry import box, shape
from shapely.strtree import STRtree
import yaml

from backend.services.geneva_service import superstructures, SERVICE


def split_for(x, y):
    group = f"{x // 512}:{y // 512}"
    bucket = int(hashlib.sha256(group.encode()).hexdigest()[:8], 16) % 10
    return group, "test" if bucket < 2 else "val" if bucket < 4 else "train"


def label_lines(geometries, bbox):
    crop = box(*bbox)
    lines = []
    for geometry in geometries:
        clipped = geometry.intersection(crop)
        parts = list(clipped.geoms) if hasattr(clipped, "geoms") else [clipped]
        for part in parts:
            if part.geom_type != "Polygon" or part.area < .15:
                continue
            if part.interiors:
                # YOLO external rings cannot represent a hole; do not silently
                # fill one and train it as occupied.
                continue
            points = list(part.simplify(.05, preserve_topology=True).exterior.coords)[:-1]
            if len(points) >= 3:
                lines.append("0 " + " ".join(f"{(x-bbox[0])/64:.6f} {(bbox[3]-y)/64:.6f}" for x, y in points))
    return lines


async def prepare(args):
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    config = {"bbox": list(args.bbox), "limit": args.limit, "version": 2}
    config_path = root / "preparation-config.json"
    if config_path.exists() and json.loads(config_path.read_text()) != config:
        raise ValueError("Use a fresh output directory when changing preparation settings")
    config_path.write_text(json.dumps(config), encoding="utf-8")
    cache = root / "source-labels.json"
    async with httpx.AsyncClient(timeout=60, limits=httpx.Limits(max_connections=5)) as client:
        if not cache.exists():
            features = await superstructures(client, args.bbox)
            cache.write_text(json.dumps(features), encoding="utf-8")
        features = json.loads(cache.read_text(encoding="utf-8"))
        geometries = [shape(f["geometry"]).buffer(0) for f in features]
        tree = STRtree(geometries)
        records = []
        for x in range(int(args.bbox[0]) // 64 * 64, int(args.bbox[2]), 64):
            for y in range(int(args.bbox[1]) // 64 * 64, int(args.bbox[3]), 64):
                if x < args.bbox[0] or y < args.bbox[1] or x+64 > args.bbox[2] or y+64 > args.bbox[3]:
                    continue
                if x % 512 in (0, 448) or y % 512 in (0, 448):
                    continue
                bbox = [x, y, x+64, y+64]
                indices = tree.query(box(*bbox), predicate="intersects").tolist()
                group, split = split_for(x, y)
                name = f"geneva_{x}_{y}"
                # Retain sampled label-empty chips as background for this
                # specific catalogue target, never call them obstruction-free.
                if not indices and int(hashlib.sha256(name.encode()).hexdigest()[:8], 16) % 5:
                    continue
                records.append({"source": name, "group": group, "split": split, "bbox": bbox,
                    "indices": indices, "egids": sorted({str(features[i]['properties'].get('EGID')) for i in indices
                        if features[i]['properties'].get('EGID') is not None})})
        egid_splits = defaultdict(set)
        for record in records:
            for egid in record["egids"]:
                egid_splits[egid].add(record["split"])
        records = [r for r in records if all(len(egid_splits[e]) == 1 for e in r["egids"])]
        records.sort(key=lambda r: hashlib.sha256(r["source"].encode()).hexdigest())
        records = records[:args.limit]
        semaphore = asyncio.Semaphore(4)
        async def download(record):
            async with semaphore:
                split, name, bbox = record["split"], record["source"], record["bbox"]
                for folder in ("images", "labels"):
                    (root / folder / split).mkdir(parents=True, exist_ok=True)
                path = root / "images" / split / (name+".jpg")
                if not path.exists():
                    for attempt in range(3):
                        try:
                            response = await client.get("https://wms.geo.admin.ch/", params={
                                "SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": "1.3.0",
                                "LAYERS": "ch.swisstopo.swissimage", "STYLES": "", "CRS": "EPSG:2056",
                                "BBOX": ",".join(map(str, bbox)), "WIDTH": 640, "HEIGHT": 640, "FORMAT": "image/jpeg"})
                            response.raise_for_status()
                            image = Image.open(io.BytesIO(response.content)).convert("RGB")
                            if image.size != (640, 640) or np.asarray(image).std() < 2:
                                raise ValueError("Invalid or blank SWISSIMAGE chip")
                            path.write_bytes(response.content)
                            break
                        except (httpx.HTTPError, ValueError, OSError):
                            if attempt == 2:
                                raise
                lines = label_lines([geometries[i] for i in record["indices"]], bbox)
                (root / "labels" / split / (name+".txt")).write_text("\n".join(lines), encoding="utf-8")
                record["objects"] = len(lines)
                record["image_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                record["survey_dates"] = sorted({features[i]["properties"]["DATE_LEVE"] for i in record["indices"]
                    if features[i]["properties"].get("DATE_LEVE") is not None})
        for start in range(0, len(records), 20):
            await asyncio.gather(*(download(r) for r in records[start:start+20]))
            print(f"Prepared {min(start+20, len(records))}/{len(records)} Geneva chips", flush=True)
        (root / "split_manifest.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
        (root / "dataset.yaml").write_text(yaml.safe_dump({"path": str(root.resolve()),
            "train": "images/train", "val": "images/val", "test": "images/test", "names": {0: "other_obstacle"}}))
        report = {"source": SERVICE, "imagery": "SWISSIMAGE / swisstopo", "crs": "EPSG:2056",
            "bbox": args.bbox, "source_labels_sha256": hashlib.sha256(cache.read_bytes()).hexdigest(),
            "metres_per_pixel": .1, "counts": dict(Counter(r["split"] for r in records)),
            "objects": dict(Counter({s: sum(r["objects"] for r in records if r["split"] == s) for s in ('train','val','test')})),
            "label_scope": "Surveyed roof superstructures; incomplete for exhaustive obstacles. No subtype labels.",
            "limitations": "Survey and current aerial acquisition dates may differ; non-true orthophoto displacement is possible. No manual label review yet.",
            "split_basis": "512 m blocks, 64 m border discarded, cross-split EGIDs removed before chip sampling"}
        (root / "dataset-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bbox", type=float, nargs=4, default=[2498000,1116000,2502000,1120000])
    parser.add_argument("--output", default="data/geneva")
    parser.add_argument("--limit", type=int, default=600)
    asyncio.run(prepare(parser.parse_args()))
