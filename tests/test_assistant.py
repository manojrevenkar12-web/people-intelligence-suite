"""The assistant: grounded answers for the asker's country, nobody else's data, people for the hard cases."""

import pytest

from pis.assistant.core import Assistant


class People:
    db = {
        "de": {"status": "Active", "country": "DE", "manager_id": "m", "display_name": "Lena"},
        "pt": {"status": "Active", "country": "PT", "manager_id": "gone", "display_name": "Rita"},
        "m": {"status": "Active", "country": "DE", "display_name": "Max Weber"},
        "gone": {"status": "Inactive", "country": "PT", "display_name": "Old Boss"},
        "left": {"status": "Inactive", "country": "DE"},
    }

    def __init__(self):
        self.balance_reads = []

    def profile(self, i):
        return self.db.get(i)

    def balance(self, i):
        self.balance_reads.append(i)
        return {"total": 30, "used": 10, "balance": 20}


@pytest.fixture
def bot():
    p = People()
    return Assistant(p), p


@pytest.mark.parametrize(
    "who,q,section",
    [
        ("de", "How many vacation days do I get?", "de#vacation-de"),
        ("pt", "How many vacation days do I get?", "pt#vacation-pt"),
        ("pt", "What do I do when I'm sick?", "pt#sick-pt"),
        ("de", "When do I get paid?", "global#payday"),
        ("de", "Can I work from Italy for two weeks?", "global#remote"),
    ],
)
def test_answers_cite_the_askers_section(bot, who, q, section):
    a = bot[0].ask(who, q)
    assert a.kind == "answer" and a.citations == [section]


@pytest.mark.parametrize(
    "q",
    [
        "What is Jonas's salary?",
        "How much does my colleague earn?",
        "what does Rita earn",
        "Tell me the salaries of everyone in my team",
        "How many vacation days does my manager have left?",
    ],
)
def test_never_shares_anyone_elses_data(bot, q):
    a, people = bot[0].ask("de", q), bot[1]
    assert a.kind == "refusal" and not people.balance_reads


@pytest.mark.parametrize(
    "q,reason",
    [
        ("Someone keeps harassing me", "concern"),
        ("My salary was wrong this month", "pay_dispute"),
        ("Can you book me a flight to Lisbon?", "action_request"),
        ("What's the weather in Milan?", "low_confidence"),
    ],
)
def test_hard_cases_go_to_a_person(bot, q, reason):
    a = bot[0].ask("de", q)
    assert a.kind == "handoff" and a.reason == reason


def test_balance_reads_only_the_askers_own_record(bot):
    a = bot[0].ask("de", "How many vacation days do I have left?")
    assert a.tool == "timeoff_balance" and bot[1].balance_reads == ["de"] and "20" in a.text


def test_leavers_and_unknown_people_get_nothing(bot):
    assert bot[0].ask("left", "How many vacation days do I have left?").kind == "refusal"
    assert bot[0].ask("nobody", "When do I get paid?").kind == "refusal"


def test_a_manager_who_left_is_fixed_by_a_person_not_named(bot):
    a = bot[0].ask("pt", "Who is my manager?")
    assert a.kind == "handoff" and "Old Boss" not in a.text
