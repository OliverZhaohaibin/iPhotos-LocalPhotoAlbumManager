from __future__ import annotations
from datetime import datetime, timezone
from iPhoto.core.pairing import pair_live

def iso(ts: datetime) -> str:
    return ts.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")

def test_mp4_content_id_pairing():
    dt = iso(datetime(2024, 1, 1, 12, 0, 0))
    rows = [
        {
            "rel": "IMG_0001.HEIC",
            "mime": "image/heic",
            "dt": dt,
            "content_id": "CID1",
        },
        {
            "rel": "IMG_0001.MP4",
            "mime": "video/mp4",
            "dt": dt,
            "content_id": "CID1",
            "dur": 1.5,
        },
    ]
    groups = pair_live(rows)

    # Expectation: Should be paired because Content ID matches
    assert len(groups) == 1, "MP4 with matching Content ID was not paired"
    group = groups[0]
    assert group.still == "IMG_0001.HEIC"
    assert group.motion == "IMG_0001.MP4"
