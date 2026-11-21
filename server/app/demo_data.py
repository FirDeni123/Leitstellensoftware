"""Fictional demo master data for development and training (region around Schwarzenbek).

All names are fictional and marked "(Demo)". Idempotent: existing records are kept.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import (
    AlarmGroup,
    ControlCenter,
    ControlCenterArea,
    Organization,
    RadioGroup,
    Ric,
    Station,
    Vehicle,
    VehicleType,
)
from app.services.uow import UnitOfWork

# name, short, organisation key, lat, lon
STATIONS = (
    ("Feuerwache Mitte (Demo)", "FW M", "feuerwehr", 53.5040, 10.4800),
    ("Feuerwache Nord (Demo)", "FW N", "feuerwehr", 53.5290, 10.4710),
    ("Feuerwache Süd (Demo)", "FW S", "feuerwehr", 53.4800, 10.4950),
    ("Rettungswache Mitte (Demo)", "RW M", "rettungsdienst", 53.5010, 10.4870),
    ("Rettungswache Ost (Demo)", "RW O", "drk", 53.5100, 10.5450),
    ("THW Ortsverband (Demo)", "THW", "thw", 53.4950, 10.4600),
)
# call sign, type code, station short name
VEHICLES = (
    ("Florian Demo 1/11-1", "ELW1", "FW M"),
    ("Florian Demo 1/46-1", "HLF20", "FW M"),
    ("Florian Demo 1/33-1", "DLK23", "FW M"),
    ("Florian Demo 1/23-1", "TLF3000", "FW M"),
    ("Florian Demo 1/19-1", "MTW", "FW M"),
    ("Florian Demo 2/46-1", "HLF20", "FW N"),
    ("Florian Demo 2/44-1", "LF20", "FW N"),
    ("Florian Demo 3/42-1", "LF10", "FW S"),
    ("Florian Demo 3/47-1", "TSF-W", "FW S"),
    ("Florian Demo 3/52-1", "RW", "FW S"),
    ("Rettung Demo 1/83-1", "RTW", "RW M"),
    ("Rettung Demo 1/83-2", "RTW", "RW M"),
    ("Rettung Demo 1/82-1", "NEF", "RW M"),
    ("Rettung Demo 1/85-1", "KTW", "RW M"),
    ("Rotkreuz Demo 2/83-1", "RTW", "RW O"),
    ("Heros Demo 21/52", "GKW", "THW"),
)
# code, sub, label, station short names
RICS = (
    ("1000101", "A", "Vollalarm FW Mitte (Demo)", ("FW M",)),
    ("1000102", "A", "Vollalarm FW Nord (Demo)", ("FW N",)),
    ("1000103", "A", "Vollalarm FW Süd (Demo)", ("FW S",)),
    ("1000110", "A", "Gemeindealarm (Demo)", ("FW M", "FW N", "FW S")),
    ("1000201", "A", "Rettungsdienst Mitte (Demo)", ("RW M",)),
)
# name, talkgroup, station short names, organisation keys
RADIO_GROUPS = (
    ("TBZ Feuerwehr (Demo)", "1001", ("FW M", "FW N", "FW S"), ("feuerwehr",)),
    ("TBZ Rettungsdienst (Demo)", "1002", ("RW M", "RW O"), ("rettungsdienst", "drk")),
    ("TBZ THW (Demo)", "1003", ("THW",), ("thw",)),
)
AREA = {
    "type": "MultiPolygon",
    "coordinates": [[[[10.40, 53.45], [10.58, 53.45], [10.58, 53.56], [10.40, 53.56], [10.40, 53.45]]]],
}


async def seed_master_data(uow: UnitOfWork, cc: ControlCenter) -> dict[str, int]:
    s = uow.session
    orgs = {o.key: o for o in (await s.scalars(select(Organization))).all()}
    types = {t.code: t for t in (await s.scalars(select(VehicleType))).all()}
    counts = {"stations": 0, "vehicles": 0, "rics": 0, "radio_groups": 0}

    stations = {
        st.short_name: st
        for st in (await s.scalars(select(Station).where(Station.control_center_id == cc.id))).all()
    }
    for name, short, org, lat, lon in STATIONS:
        if short not in stations and org in orgs:
            st = Station(
                control_center_id=cc.id,
                organization_id=orgs[org].id,
                name=name,
                short_name=short,
                latitude=lat,
                longitude=lon,
                availability={"mode": "always"},
            )
            s.add(st)
            stations[short] = st
            counts["stations"] += 1
    await s.flush()

    rics = {
        (r.code, r.sub_address): r
        for r in (await s.scalars(select(Ric).where(Ric.control_center_id == cc.id))).all()
    }
    for code, sub, label, station_keys in RICS:
        if (code, sub) not in rics:
            ric = Ric(
                control_center_id=cc.id,
                code=code,
                sub_address=sub,
                label=label,
                stations=[stations[k] for k in station_keys if k in stations],
            )
            s.add(ric)
            rics[(code, sub)] = ric
            counts["rics"] += 1

    groups = {
        g.name: g
        for g in (await s.scalars(select(RadioGroup).where(RadioGroup.control_center_id == cc.id))).all()
    }
    for name, talkgroup, station_keys, org_keys in RADIO_GROUPS:
        if name not in groups:
            g = RadioGroup(
                control_center_id=cc.id,
                name=name,
                talkgroup=talkgroup,
                stations=[stations[k] for k in station_keys if k in stations],
                organizations=[orgs[k] for k in org_keys if k in orgs],
            )
            s.add(g)
            groups[name] = g
            counts["radio_groups"] += 1
    await s.flush()

    if not await s.scalar(select(AlarmGroup).where(AlarmGroup.control_center_id == cc.id)):
        s.add(
            AlarmGroup(
                control_center_id=cc.id,
                name="Gemeindealarm (Demo)",
                rics=[rics[(c, "A")] for c in ("1000101", "1000102", "1000103", "1000110")],
            )
        )
    if not await s.scalar(select(ControlCenterArea).where(ControlCenterArea.control_center_id == cc.id)):
        s.add(
            ControlCenterArea(
                control_center_id=cc.id, name="Demo-Bereich Schwarzenbek", geometry=AREA, priority=10
            )
        )

    existing = {
        v.call_sign
        for v in (await s.scalars(select(Vehicle).where(Vehicle.control_center_id == cc.id))).all()
    }
    group_for_org = {
        "feuerwehr": "TBZ Feuerwehr (Demo)",
        "rettungsdienst": "TBZ Rettungsdienst (Demo)",
        "drk": "TBZ Rettungsdienst (Demo)",
        "thw": "TBZ THW (Demo)",
    }
    for call_sign, code, short in VEHICLES:
        st = stations.get(short)
        if call_sign in existing or st is None or code not in types:
            continue
        org = st.organization_id
        org_key = next(k for k, o in orgs.items() if o.id == org)
        own_rics = [r for r in rics.values() if st in r.stations and r.code != "1000110"]
        s.add(
            Vehicle(
                control_center_id=cc.id,
                station_id=st.id,
                organization_id=org,
                vehicle_type_id=types[code].id,
                call_sign=call_sign,
                status_code=2,
                radio_group_id=groups[group_for_org[org_key]].id,
                crew_size=types[code].default_crew,
                rics=own_rics,
            )
        )
        counts["vehicles"] += 1
    await s.flush()
    if any(counts.values()):
        uow.audit(
            "seed",
            "demo_data",
            cc.id,
            f"Demo-Stammdaten angelegt ({counts['stations']} Wachen, {counts['vehicles']} Fahrzeuge, "
            f"{counts['rics']} RICs, {counts['radio_groups']} Funkrufgruppen)",
            control_center_id=cc.id,
        )
    return counts
