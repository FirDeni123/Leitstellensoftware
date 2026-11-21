"""Simulated telephony (Phase 3): generates incoming emergency calls for training.

This provider is the *only* source of simulated calls. It never touches real telephony –
real VoIP will be a separate provider (``is_real = True``) in phase 7. Simulated calls are
refused while the system runs in real operation mode (see the router).

All persons, phone numbers and addresses are fictional ("Demostadt"). Phone numbers use the
``0000`` block so they cannot be mistaken for real subscribers.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

IS_REAL = False


@dataclass(frozen=True, slots=True)
class Scenario:
    key: str
    title: str
    expected_keyword: str  # used by the training evaluation in phase 7
    transcript: str
    location_hint: str | None = None


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "pkw_brand",
        "Pkw-Brand auf Parkplatz",
        "B2",
        "Hallo? Hier brennt ein Auto auf dem Parkplatz! Da kommt ganz viel schwarzer Rauch raus!",
        "Parkplatz",
    ),
    Scenario(
        "kuechenbrand_person",
        "Küchenbrand, Person vermisst",
        "B-MIG",
        "Bei meinen Nachbarn brennt es in der Küche, ich glaube, die ältere Frau ist noch in der Wohnung!",
    ),
    Scenario(
        "kellerbrand",
        "Rauch aus dem Keller",
        "B2",
        "Aus dem Keller vom Mehrfamilienhaus kommt Rauch, im Treppenhaus riecht es total verbrannt.",
    ),
    Scenario(
        "vu_eingeklemmt",
        "Verkehrsunfall, Person eingeklemmt",
        "H-KLEMM",
        "Hier ist ein schwerer Unfall, zwei Autos! Einer ist eingeklemmt und blutet am Kopf!",
        "Kreuzung",
    ),
    Scenario(
        "bewusstlos",
        "Person bewusstlos, Atmung auffällig",
        "RD2",
        "Mein Mann ist plötzlich umgekippt und atmet ganz komisch, bitte kommen Sie schnell!",
    ),
    Scenario(
        "sturz",
        "Sturz einer älteren Person",
        "RD1",
        "Meine Mutter ist gestürzt und kann nicht mehr aufstehen, die Hüfte tut ihr weh.",
    ),
    Scenario(
        "oelspur",
        "Ölspur auf der Fahrbahn",
        "H1",
        "Auf der Straße ist eine lange Ölspur, die Autos rutschen da schon rum.",
    ),
    Scenario(
        "baum", "Baum auf Fahrbahn", "H1", "Ein Baum ist auf die Straße gefallen, man kommt nicht mehr durch."
    ),
    Scenario(
        "bma",
        "Brandmeldeanlage ausgelöst",
        "BMA",
        "Hier ist der Sicherheitsdienst, bei uns hat die Brandmeldeanlage im Lager ausgelöst.",
    ),
    Scenario(
        "person_im_wasser",
        "Person im Wasser",
        "W1",
        "Da ist jemand im See untergegangen, ich sehe ihn nicht mehr!",
        "Badestelle",
    ),
)
SCENARIO_BY_KEY = {s.key: s for s in SCENARIOS}

# Fictional addresses inside the demo area of responsibility.
ADDRESSES: tuple[tuple[str, float, float], ...] = (
    ("Bahnhofstraße 12, 21493 Demostadt", 53.5035, 10.4795),
    ("Lindenweg 4, 21493 Demostadt", 53.5091, 10.4712),
    ("Industriestraße 30, 21493 Demostadt", 53.4952, 10.4968),
    ("Am Markt 1, 21493 Demostadt", 53.5049, 10.4822),
    ("Waldweg 7, 21493 Demodorf", 53.5260, 10.4630),
    ("Schulstraße 18, 21493 Demostadt", 53.5012, 10.4851),
    ("Kreuzung Hauptstraße / Mühlenweg, Demostadt", 53.5068, 10.4901),
    ("Badestelle Demosee, 21493 Demodorf", 53.5150, 10.5300),
)
FIRST_NAMES = ("Anna", "Peter", "Maria", "Thomas", "Sabine", "Jonas", "Elif", "Mehmet", "Lena", "Klaus")
LAST_NAMES = ("Muster", "Beispiel", "Probe", "Demo", "Testmann", "Fiktiv", "Simul", "Übung")


@dataclass(frozen=True, slots=True)
class SimulatedCall:
    scenario: Scenario
    caller_name: str
    caller_phone: str
    caller_location: str | None
    caller_latitude: float | None
    caller_longitude: float | None
    true_address: str
    true_latitude: float
    true_longitude: float


def generate(scenario_key: str | None = None, rng: random.Random | None = None) -> SimulatedCall:
    rng = rng or random.Random()  # noqa: S311 – simulation content, not security relevant
    scenario = SCENARIO_BY_KEY[scenario_key] if scenario_key else rng.choice(SCENARIOS)
    address, lat, lon = rng.choice(ADDRESSES)
    # Mobile callers often transmit a location (AML) with some inaccuracy; landlines do not.
    mobile = rng.random() < 0.7
    phone = f"0151 0000 {rng.randint(1000, 9999)}" if mobile else f"04151 0000 {rng.randint(10, 99)}"
    jitter = rng.uniform(0.0004, 0.003)
    return SimulatedCall(
        scenario=scenario,
        caller_name=f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
        caller_phone=phone,
        caller_location=f"Mobilfunkortung ±{int(jitter * 111000)} m" if mobile else None,
        caller_latitude=round(lat + rng.uniform(-jitter, jitter), 6) if mobile else None,
        caller_longitude=round(lon + rng.uniform(-jitter, jitter), 6) if mobile else None,
        true_address=address,
        true_latitude=lat,
        true_longitude=lon,
    )
