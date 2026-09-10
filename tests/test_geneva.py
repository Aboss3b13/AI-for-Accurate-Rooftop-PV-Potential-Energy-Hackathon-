import asyncio
import json
from pathlib import Path

import httpx
import pytest
from shapely.geometry import box, mapping
from backend.services.geneva_service import superstructures, surveyed_polygons
from training.prepare_geneva import label_lines, split_for


def test_geneva_pagination_and_coordinate_system():
    offsets = []
    def handler(request):
        offset = int(request.url.params["resultOffset"])
        offsets.append(offset)
        return httpx.Response(200, json={"crs": {"properties": {"name": "EPSG:2056"}},
            "features": [{"id": offset}], "exceededTransferLimit": offset == 0})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await superstructures(client, (2499000,1117000,2499100,1117100))
    assert len(asyncio.run(run())) == 2
    assert offsets == [0, 4000]


def test_geneva_does_not_query_outside_coverage():
    assert asyncio.run(superstructures(None, (2600000,1200000,2600100,1200100))) == []


def test_unexpected_crs_is_rejected():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200,
            json={"crs": {"properties": {"name": "EPSG:4326"}}, "features": []}))) as client:
            await superstructures(client, (2499000,1117000,2499100,1117100))
    with pytest.raises(ValueError, match="coordinate system"):
        asyncio.run(run())


def test_training_labels_use_north_up_metric_coordinates():
    bounds = (2499000,1117000,2499064,1117064)
    polygon = box(2499016,1117016,2499048,1117048)
    line = label_lines([polygon], bounds)[0]
    points = list(map(float, line.split()[1:]))
    assert set(points) == {.25,.75}
    assert split_for(2499072,1117056) == split_for(2499136,1117120)


def test_surveyed_obstacles_are_clipped_to_roof():
    feature = {"geometry": mapping(box(0,0,8,8)), "properties": {"EGID": 1}}
    result = list(surveyed_polygons([feature], box(4,4,10,10)))
    assert result[0][0].area == 16


def test_geneva_split_has_no_egid_or_block_leakage():
    manifest = Path("data/geneva_clean/split_manifest.json")
    if not manifest.exists():
        pytest.skip("Downloaded Geneva dataset is optional")
    records = json.loads(manifest.read_text())
    for field in ("group", "egids"):
        seen = {}
        for record in records:
            values = [record[field]] if field == "group" else record[field]
            for value in values:
                assert seen.setdefault(value, record["split"]) == record["split"]
