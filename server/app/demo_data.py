"""Fictional demo master data for development and training (region around Schwarzenbek).

All names are fictional and marked "(Demo)". Idempotent: existing records are kept.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import (
    AlarmGroup,
    AlarmRule,
    AlarmRuleItem,
    ControlCenter,
    ControlCenterArea,
    Interface,
    InterfaceEvent,
    Keyword,
    Organization,
    RadioGroup,
    Ric,
    Station,
    TrainingScenario,
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
# keyword code -> ((stage, vehicle type code, count), ...) – fictional demo AAO
ALARM_RULES: dict[str, tuple[tuple[int, str, int], ...]] = {
    "B1": ((1, "HLF20", 1), (2, "TLF3000", 1)),
    "B2": ((1, "HLF20", 1), (1, "DLK23", 1), (1, "ELW1", 1), (2, "HLF20", 2), (2, "RTW", 1)),
    "B3": (
        (1, "HLF20", 2),
        (1, "DLK23", 1),
        (1, "ELW1", 1),
        (1, "TLF3000", 1),
        (1, "RTW", 1),
        (2, "LF20", 1),
        (2, "LF10", 1),
        (2, "RW", 1),
    ),
    "B-MIG": ((1, "HLF20", 2), (1, "DLK23", 1), (1, "ELW1", 1), (1, "RTW", 1), (1, "NEF", 1)),
    "BMA": ((1, "HLF20", 1), (1, "DLK23", 1)),
    "H1": ((1, "HLF20", 1),),
    "H2": ((1, "HLF20", 1), (1, "RTW", 1), (1, "NEF", 1), (2, "RW", 1)),
    "H-KLEMM": ((1, "HLF20", 2), (1, "RW", 1), (1, "ELW1", 1), (1, "RTW", 1), (1, "NEF", 1)),
    "W1": ((1, "HLF20", 1), (1, "RTW", 1), (1, "NEF", 1)),
    "RD1": ((1, "RTW", 1),),
    "RD2": ((1, "RTW", 1), (1, "NEF", 1)),
    "RD-KTP": ((1, "KTW", 1),),
    "MANV": ((1, "RTW", 3), (1, "NEF", 1), (1, "ELW1", 1), (2, "GKW", 1)),
}
DEMO_INTERFACE = "Simulations-Empfänger (Demo)"

# Fictional training scenarios for the AI caller (persons, numbers and addresses invented;
# numbers in the 0000 block). keyword code, difficulty, persona, facts, opening line, checklist.
TRAINING_SCENARIOS: tuple[dict, ...] = (
    {
        "title": "Pkw-Brand auf dem Parkplatz (Demo)",
        "description": "Brennendes Auto auf einem Supermarktparkplatz, Anrufer ist Passant.",
        "difficulty": "easy",
        "keyword": "B2",
        "persona": {
            "name": "Jonas Beispiel",
            "age": 34,
            "role": "Passant mit Einkaufswagen",
            "emotional_state": "angespannt, aber ruhig",
            "speech_style": "kurze, klare Sätze",
            "phone": "0000 1234567",
        },
        "facts": {
            "address": "Industriestraße 30, 21493 Demostadt",
            "lat": 53.4952,
            "lon": 10.4968,
            "location_hint": "Parkplatz vor dem Supermarkt, hintere Reihe am Zaun",
            "situation": "Ein geparkter Kleinwagen brennt im Motorraum, Flammen schlagen unter der Haube hervor.",
            "persons": "Niemand im Auto, der Besitzer ist nicht zu sehen.",
            "injuries": "Keine Verletzten.",
            "hazards": "Daneben stehen zwei weitere Autos, schwarzer Rauch zieht Richtung Eingang.",
            "details": ["Das Auto ist ein roter Kleinwagen.", "Leute gehen schon auf Abstand."],
            "unknown": ["Wem das Auto gehört", "Ob es ein Elektroauto ist"],
        },
        "opening_line": "Ja hallo, hier brennt ein Auto auf dem Parkplatz vom Supermarkt!",
        "checklist": [],
    },
    {
        "title": "Verkehrsunfall, Person eingeklemmt (Demo)",
        "description": "Pkw gegen Baum auf der Landstraße, Fahrer im Fahrzeug eingeklemmt.",
        "difficulty": "medium",
        "keyword": "H-KLEMM",
        "persona": {
            "name": "Sabine Muster",
            "age": 52,
            "role": "Ersthelferin, hat angehalten",
            "emotional_state": "aufgeregt, außer Atem",
            "speech_style": "spricht schnell, wiederholt sich",
            "phone": "0000 2345678",
        },
        "facts": {
            "address": "Kreuzung Hauptstraße / Mühlenweg, Demostadt",
            "lat": 53.5068,
            "lon": 10.4901,
            "location_hint": "ca. 200 m hinter der Kreuzung Richtung Demodorf, rechts am Baum",
            "situation": "Ein Pkw ist von der Straße abgekommen und frontal gegen einen Baum geprallt.",
            "persons": "Eine Person, der Fahrer, allein im Auto.",
            "injuries": "Fahrer ist ansprechbar, blutet am Kopf, Beine eingeklemmt, kommt nicht raus.",
            "hazards": "Aus dem Motorraum dampft es, kein Feuer. Auto steht halb auf der Fahrbahn.",
            "details": ["Die Fahrertür klemmt.", "Ein zweiter Autofahrer sichert mit Warndreieck ab."],
            "unknown": ["Name des Fahrers", "Ob der Fahrer Medikamente nimmt"],
        },
        "opening_line": "Hallo? Hier ist ein Unfall, ein Auto ist gegen einen Baum, der Mann kommt nicht raus!",
        "checklist": [
            {
                "key": "ask_location",
                "label": "Genauen Unfallort erfragt",
                "required": True,
                "hints": ["wo", "straße", "richtung", "kreuzung"],
            },
            {
                "key": "ask_persons",
                "label": "Anzahl Beteiligte erfragt",
                "required": True,
                "hints": ["wie viele", "personen", "jemand"],
            },
            {
                "key": "ask_trapped",
                "label": "Eingeklemmte Person erkannt/erfragt",
                "required": True,
                "hints": ["eingeklemmt", "raus", "befreien"],
            },
            {
                "key": "ask_condition",
                "label": "Zustand (Bewusstsein, Atmung) erfragt",
                "required": True,
                "hints": ["ansprechbar", "bewusst", "atmet", "blut"],
            },
            {
                "key": "ask_hazards",
                "label": "Gefahren (Brand, Verkehr) erfragt",
                "required": False,
                "hints": ["brennt", "feuer", "rauch", "verkehr"],
            },
            {
                "key": "ask_callback",
                "label": "Rückrufnummer erfragt",
                "required": True,
                "hints": ["nummer", "rückruf"],
            },
            {
                "key": "give_advice",
                "label": "Eigensicherung/Verhaltenshinweise gegeben",
                "required": False,
                "hints": ["sichern", "abstand", "warnweste", "bleiben sie"],
            },
        ],
    },
    {
        "title": "Brustschmerz, Verdacht Herzinfarkt (Demo)",
        "description": "Ehefrau meldet starke Brustschmerzen ihres Mannes in der Wohnung.",
        "difficulty": "medium",
        "keyword": "RD2",
        "persona": {
            "name": "Maria Probe",
            "age": 67,
            "role": "Ehefrau des Patienten",
            "emotional_state": "besorgt, zittrige Stimme",
            "speech_style": "höflich, etwas umständlich",
            "phone": "0000 3456789",
        },
        "facts": {
            "address": "Lindenweg 4, 21493 Demostadt",
            "lat": 53.5091,
            "lon": 10.4712,
            "location_hint": "Erdgeschoss rechts, Name Probe an der Klingel",
            "situation": "Ehemann (70) hat seit 20 Minuten starke Schmerzen in der Brust, die in den linken Arm ziehen.",
            "persons": "Der Ehemann, sie ist mit ihm allein.",
            "injuries": "Er ist ansprechbar, schwitzt stark, ist blass und hat Atemnot. Er hatte schon einmal einen Stent.",
            "hazards": "Keine.",
            "details": ["Er sitzt im Sessel im Wohnzimmer.", "Die Haustür ist abgeschlossen."],
            "unknown": ["Welche Medikamente er genau nimmt"],
        },
        "opening_line": "Guten Tag, bitte, meinem Mann geht es ganz schlecht, er hat so Schmerzen in der Brust.",
        "checklist": [
            {
                "key": "ask_location",
                "label": "Adresse mit Klingel/Etage erfragt",
                "required": True,
                "hints": ["adresse", "wo", "straße", "klingel", "etage"],
            },
            {
                "key": "ask_symptoms",
                "label": "Beschwerden genauer erfragt",
                "required": True,
                "hints": ["schmerz", "seit wann", "arm", "atemnot"],
            },
            {
                "key": "ask_conscious",
                "label": "Bewusstsein und Atmung erfragt",
                "required": True,
                "hints": ["ansprechbar", "bewusst", "atmet"],
            },
            {
                "key": "ask_history",
                "label": "Vorerkrankungen erfragt",
                "required": False,
                "hints": ["vorerkrank", "herz", "medikament"],
            },
            {
                "key": "ask_callback",
                "label": "Rückrufnummer erfragt",
                "required": True,
                "hints": ["nummer", "rückruf"],
            },
            {
                "key": "give_advice",
                "label": "Hinweise gegeben (Tür öffnen, nicht allein lassen)",
                "required": True,
                "hints": ["tür", "aufschließen", "bleiben sie", "hinsetzen", "oberkörper"],
            },
        ],
    },
    {
        "title": "Küchenbrand, Person in der Wohnung (Demo)",
        "description": "Panischer Anrufer, Rauch im Treppenhaus, Nachbarin vermutlich noch in der Wohnung.",
        "difficulty": "hard",
        "keyword": "B-MIG",
        "persona": {
            "name": "Mehmet Fiktiv",
            "age": 23,
            "role": "Nachbar aus dem 1. Stock",
            "emotional_state": "panisch, schreit zwischendurch",
            "speech_style": "abgehackt, beantwortet nicht immer die gestellte Frage",
            "phone": "0000 4567890",
        },
        "facts": {
            "address": "Schulstraße 18, 21493 Demostadt",
            "lat": 53.5012,
            "lon": 10.4851,
            "location_hint": "Mehrfamilienhaus, Brandwohnung 2. Obergeschoss links",
            "situation": "Aus der Wohnung über ihm dringt dichter Rauch, im Küchenfenster sind Flammen zu sehen.",
            "persons": "Die ältere Nachbarin (ca. 80) wohnt allein dort und öffnet nicht. Weitere Bewohner sind im Haus.",
            "injuries": "Unbekannt, die Nachbarin antwortet nicht.",
            "hazards": "Treppenhaus voller Rauch, er ist selbst noch in seiner Wohnung im 1. OG.",
            "details": ["Er hört Rauchmelder piepen.", "Seine Wohnungstür ist zu."],
            "unknown": ["Ob die Nachbarin zu Hause ist", "Wie viele Leute noch im Haus sind"],
        },
        "opening_line": "Feuer! Es brennt bei uns im Haus, da ist überall Rauch!",
        "checklist": [
            {
                "key": "ask_location",
                "label": "Adresse und Brandgeschoss erfragt",
                "required": True,
                "hints": ["adresse", "wo", "straße", "stock", "etage", "geschoss"],
            },
            {
                "key": "ask_persons",
                "label": "Vermisste/eingeschlossene Personen erfragt",
                "required": True,
                "hints": ["jemand", "personen", "noch drin", "nachbarin", "menschen"],
            },
            {
                "key": "ask_caller_safe",
                "label": "Eigene Lage des Anrufers erfragt",
                "required": True,
                "hints": ["wo sind sie", "in sicherheit", "ihre wohnung", "rauch bei ihnen"],
            },
            {
                "key": "give_advice",
                "label": "Verhaltenshinweis: Tür zu, nicht ins Treppenhaus, am Fenster bemerkbar machen",
                "required": True,
                "hints": ["tür zu", "nicht ins treppenhaus", "fenster", "bleiben sie", "tür geschlossen"],
            },
            {
                "key": "ask_callback",
                "label": "Rückrufnummer erfragt",
                "required": True,
                "hints": ["nummer", "rückruf"],
            },
        ],
    },
)

AREA = {
    "type": "MultiPolygon",
    "coordinates": [[[[10.40, 53.45], [10.58, 53.45], [10.58, 53.56], [10.40, 53.56], [10.40, 53.45]]]],
}


async def seed_master_data(uow: UnitOfWork, cc: ControlCenter) -> dict[str, int]:
    s = uow.session
    orgs = {o.key: o for o in (await s.scalars(select(Organization))).all()}
    types = {t.code: t for t in (await s.scalars(select(VehicleType))).all()}
    counts = {"stations": 0, "vehicles": 0, "rics": 0, "radio_groups": 0, "training_scenarios": 0}

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
    counts["alarm_rules"] = await _seed_alarming(uow, cc, types)
    counts["training_scenarios"] = await _seed_training(uow, cc)
    if any(counts.values()):
        uow.audit(
            "seed",
            "demo_data",
            cc.id,
            f"Demo-Stammdaten angelegt ({counts['stations']} Wachen, {counts['vehicles']} Fahrzeuge, "
            f"{counts['rics']} RICs, {counts['radio_groups']} Funkrufgruppen, "
            f"{counts['alarm_rules']} AAO, {counts['training_scenarios']} Übungsszenarien)",
            control_center_id=cc.id,
        )
    return counts


async def _seed_training(uow: UnitOfWork, cc: ControlCenter) -> int:
    s = uow.session
    keywords = {k.code: k for k in (await s.scalars(select(Keyword))).all()}
    existing = set(
        (
            await s.scalars(select(TrainingScenario.title).where(TrainingScenario.control_center_id == cc.id))
        ).all()
    )
    created = 0
    for raw in TRAINING_SCENARIOS:
        if raw["title"] in existing:
            continue
        data = dict(raw)
        keyword = keywords.get(data.pop("keyword"))
        s.add(TrainingScenario(control_center_id=cc.id, keyword_id=keyword.id if keyword else None, **data))
        created += 1
    await s.flush()
    return created


async def _seed_alarming(uow: UnitOfWork, cc: ControlCenter, types: dict[str, VehicleType]) -> int:
    """Demo AAO per keyword and an (enabled) simulation receiver – never a real interface."""
    s = uow.session
    keywords = {k.code: k for k in (await s.scalars(select(Keyword))).all()}
    existing = set(
        (await s.scalars(select(AlarmRule.keyword_id).where(AlarmRule.control_center_id == cc.id))).all()
    )
    created = 0
    for code, items in ALARM_RULES.items():
        keyword = keywords.get(code)
        if keyword is None or keyword.id in existing:
            continue
        rule = AlarmRule(control_center_id=cc.id, keyword_id=keyword.id, name=f"{code} (Demo)")
        rule.items = [
            AlarmRuleItem(
                stage=stage, position=pos, kind="vehicle_type", count=count, vehicle_type_id=types[t].id
            )
            for pos, (stage, t, count) in enumerate(items)
            if t in types
        ]
        s.add(rule)
        created += 1
    if not await s.scalar(select(Interface.id).where(Interface.name == DEMO_INTERFACE)):
        interface = Interface(
            plugin_key="simulation_receiver",
            name=DEMO_INTERFACE,
            scope="control_center",
            control_center_id=cc.id,
            enabled=True,  # simulation plugin (is_real=False): no external system is contacted
            config={"receiver_label": "Übungs-Alarmierungs-App (Demo)"},
        )
        s.add(interface)
        await s.flush()
        s.add(
            InterfaceEvent(
                interface_id=interface.id, level="info", kind="config", message="Demo-Schnittstelle angelegt"
            )
        )
    await s.flush()
    return created
