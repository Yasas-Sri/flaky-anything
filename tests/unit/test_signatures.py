from datetime import datetime, timezone

from flaky_anything.config import TrialConfig
from flaky_anything.runner import TrialResult
from flaky_anything.signatures import group, signature, signatures_for
from flaky_anything.trial_plugin import NodeResult, redact_env

# Real --tb=long output captured from the corpus (Python 3.14).
T1 = """def test_next_month_invoice():
        \"\"\"T1: production bug in billing.next_month on month ends and in December.\"\"\"
        today = date.today()
>       assert billing.next_month(today).month == today.month % 12 + 1
               ^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_time.py:9: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

d = datetime.date(2027, 1, 31)

    def next_month(d: date) -> date:
        \"\"\"Same day next month. BUG: fails on the 29th-31st and in December.\"\"\"
>       return d.replace(month=d.month + 1)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       ValueError: day is out of range for month

corpuslib/billing.py:8: ValueError"""

O1 = """def test_lookup_empty_cache():
        \"\"\"O1 victim: assumes the module-level cache starts empty.\"\"\"
>       assert cache.size() == 0
E       assert 1 == 0
E        +  where 1 = <function size at 0x7f6187fe4400>()
E        +    where <function size at 0x7f6187fe4400> = cache.size

tests/test_order.py:8: AssertionError"""


def test_parses_type_frames_and_message() -> None:
    sig = signature(T1)
    assert sig.exc_type == "ValueError"
    assert sig.normalized_frames.splitlines() == [
        "tests/test_time.py: assert billing.next_month(today).month == today.month % 12 + 1",
        "corpuslib/billing.py: return d.replace(month=d.month + 1)",
    ]
    assert sig.sample_longrepr == T1


def test_masks_addresses_and_numbers() -> None:
    other_run = O1.replace("0x7f6187fe4400", "0x7fabcdef0001").replace(
        "assert 1 == 0", "assert 3 == 0"
    )
    assert signature(other_run).id == signature(O1).id


def test_ignores_line_numbers_and_py311_carets() -> None:
    moved = T1.replace("test_time.py:9:", "test_time.py:42:").replace(
        "billing.py:8:", "billing.py:9:"
    )
    py310 = "\n".join(line for line in T1.splitlines() if set(line.strip()) != {"^"})
    assert signature(moved).id == signature(T1).id
    assert signature(py310).id == signature(T1).id


def test_masks_tmp_and_venv_paths() -> None:
    def failure(path: str, site: str) -> str:
        return (
            f">       open(path)\nE       FileNotFoundError: '{path}'\n\n"
            f"{site}/site-packages/lib/io.py:3: FileNotFoundError"
        )

    a = failure("/tmp/pytest-of-ann/pytest-12/test_x0/data.json", "/home/ann/.venv/lib/python3.13")
    b = failure("/tmp/pytest-of-bob/pytest-7/test_x0/data.json", "/opt/env/lib/python3.10")
    assert signature(a).id == signature(b).id


def test_different_causes_get_different_ids() -> None:
    other_exc = T1.replace("ValueError", "TypeError")
    other_line = O1.replace("assert cache.size() == 0", "assert cache.size() == 1")
    assert len({signature(T1).id, signature(other_exc).id, signature(O1).id}) == 3
    assert signature(other_line).id != signature(O1).id


def test_signatures_for_trial_covers_failures_timeouts_and_crashes() -> None:
    def node(name: str, outcome: str, longrepr: str | None = None) -> NodeResult:
        return NodeResult(nodeid=name, outcome=outcome, phase="call", duration=0, longrepr=longrepr)  # type: ignore[arg-type]

    result = TrialResult(
        trial_id="t",
        config=TrialConfig(nodeids=["x"]),
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        duration=1,
        status="timeout",
        results=[
            node("p", "passed"),
            node("s", "skipped"),
            node("f", "failed", O1),
            node("h", "timeout"),
        ],
    )
    sigs = signatures_for(result)
    assert set(sigs) == {"f", "h"}
    assert sigs["f"].id == signature(O1).id
    assert sigs["h"].exc_type == "Timeout"


def test_group_by_signature_keeps_order() -> None:
    a, b = signature(O1), signature(T1)
    assert group([("t1", a), ("t2", b), ("t3", a)]) == {a.id: ["t1", "t3"], b.id: ["t2"]}


def test_environ_reprs_are_redacted_and_do_not_split_signatures() -> None:
    def failure(env: str) -> str:
        return (
            "    def test_x():\n"
            '>       assert os.environ.get("MODE") == "fast"\n'
            "E       AssertionError: assert None == 'fast'\n"
            "E        +  where None = get('MODE')\n"
            f"E        +    where get = environ({{{env}}}).get\n"
            "\n"
            "tests/test_x.py:4: AssertionError"
        )

    a = signature(failure("'TOKEN': 's3cr3t', 'FLAKY_ANYTHING_RESULT': '/r/aaaa.jsonl'"))
    b = signature(failure("'TZ': 'Asia/Colombo', 'FLAKY_ANYTHING_RESULT': '/r/bbbb.jso..."))
    assert a.id == b.id
    assert "s3cr3t" not in a.sample_longrepr  # the stored sample is redacted too
    assert redact_env("x = environ({'TOKEN': 's3cr3t'}).get('A')") == "x = environ({...}).get('A')"
    assert redact_env("where environ({'TOKEN': 's3cr3t', 'B': 'tru...") == "where environ({...})"
