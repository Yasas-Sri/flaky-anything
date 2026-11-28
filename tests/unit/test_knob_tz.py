import random

from flaky_anything.config import TrialConfig
from flaky_anything.knobs.base import Knob
from flaky_anything.knobs.tz import ZONES, TzKnob

knob = TzKnob()
CFG = TrialConfig(nodeids=["t.py::a"])


def test_tz_knob_contract() -> None:
    k: Knob[str] = knob
    assert isinstance(k, Knob)
    assert knob.baseline() == "UTC"
    assert knob.sample(random.Random(4), CFG) == knob.sample(random.Random(4), CFG)
    assert {knob.sample(random.Random(s), CFG) for s in range(200)} == set(ZONES)
    for zone in ZONES:  # every zone is a valid IANA name (apply re-validates)
        applied = knob.apply(CFG, zone)
        assert TrialConfig.model_validate_json(applied.canonical_json()).tz == zone
    assert knob.describe("Asia/Colombo") == "tz: Asia/Colombo"
    assert knob.plain_pytest_repro("Asia/Colombo") == "TZ=Asia/Colombo"
