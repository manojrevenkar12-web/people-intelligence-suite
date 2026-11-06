"""The People self-service assistant.

It answers the repetitive questions from the handbook for the asker's country and always cites the
section; it reads the asker's own HiBob data (vacation balance, manager) and nobody else's; it sends
concerns, disputes and anything it cannot ground to a person. Decisions are rules in code, so they can
be read, tested and changed by the People team; a language model may phrase an answer, never choose it.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pis.settings import policy

POLICIES = Path(__file__).parent / "policies"
SYNONYMS = {
    "holiday": "vacation",
    "holidays": "vacation",
    "pto": "vacation",
    "annual": "vacation",
    "urlaub": "vacation",
    "vacaciones": "vacation",
    "ferie": "vacation",
    "ferias": "vacation",
    "leave": "leave",
    "days": "days",
    "ill": "sick",
    "illness": "sick",
    "sickness": "sick",
    "krank": "sick",
    "doctor": "sick",
    "certificate": "sick",
    "maternity": "parental",
    "paternity": "parental",
    "baby": "parental",
    "child": "parental",
    "elternzeit": "parental",
    "salary": "pay",
    "salaries": "pay",
    "payslips": "payslip",
    "payslip": "payslip",
    "paycheck": "payslip",
    "wage": "pay",
    "raise": "review",
    "increase": "review",
    "promotion": "review",
    "abroad": "workation",
    "travel": "workation",
    "anywhere": "remote",
    "laptop": "home",
    "desk": "home",
    "chair": "home",
    "monitor": "home",
    "screen": "home",
    "course": "learning",
    "training": "learning",
    "conference": "learning",
    "books": "learning",
    "receipt": "expenses",
    "reimburse": "expenses",
    "reimbursement": "expenses",
    "expense": "expenses",
    "quit": "leaving",
    "resign": "leaving",
    "resignation": "leaving",
    "notice": "leaving",
    "address": "personal",
    "bank": "personal",
    "iban": "personal",
    # how expenses are asked about
    "reimbursed": "expenses",
    "refund": "expenses",
    "refunded": "expenses",
    "train": "expenses",
    "ticket": "expenses",
    "flight": "expenses",
    "hotel": "expenses",
    "taxi": "expenses",
    # the same words in German, Spanish, Portuguese and Italian
    "tage": "days",
    "dias": "days",
    "días": "days",
    "giorni": "days",
    "ferien": "vacation",
    "vacanze": "vacation",
    "férias": "vacation",
    "krankmeldung": "sick",
    "krankschreibung": "sick",
    "baja": "sick",
    "enfermo": "sick",
    "doente": "sick",
    "malattia": "sick",
    "malato": "sick",
    "gehalt": "pay",
    "lohn": "pay",
    "salario": "pay",
    "salário": "pay",
    "stipendio": "pay",
    "nómina": "payslip",
    "nomina": "payslip",
    "gehaltsabrechnung": "payslip",
    "recibo": "payslip",
    "busta": "payslip",
    "reembolso": "expenses",
    "rimborso": "expenses",
    "spesen": "expenses",
    "gastos": "expenses",
    "despesas": "expenses",
    "spese": "expenses",
    "kündigung": "leaving",
    "kündigen": "leaving",
    "dimisiones": "leaving",
    "dimissioni": "leaving",
    "despedimento": "leaving",
    "mutterschutz": "parental",
    "maternidad": "parental",
    "paternidad": "parental",
    "maternità": "parental",
    "paternità": "parental",
    "parentalidade": "parental",
    "permiso": "leave",
    "licença": "leave",
    "congedo": "leave",
    "homeoffice": "remote",
    "teletrabajo": "remote",
    "teletrabalho": "remote",
    "smartworking": "remote",
}
STOP = set(
    "a an the i my me to of in for on is are do does can how what when where who which with and or be "
    "we our you your it at from this that have has get much many any about need want will would should "
    "there week weeks month months year years "
    # the commonest function words in German, Spanish, Portuguese and Italian
    "de la el los las il lo gli le da do dos das di del della und der die das ein eine ich mein meine "
    "que per para por em en com con mit io eu yo mi mio minha mis quanto quantos quantas cuantos cuantas "
    "cuánto cuántos wie viele welche wann quando cuando como come wo dove onde".split()
)
COUNTRIES = {
    "germany",
    "spain",
    "portugal",
    "italy",
    "france",
    "netherlands",
    "austria",
    "greece",
    "poland",
    "belgium",
    "ireland",
    "croatia",
    "eu",
    "europe",
}
CONCERN = re.compile(
    r"harass|discriminat|bull(y|ied|ying)|unsafe|mobbing|threat|assault|grievance|retaliat|"
    r"whistleblow|sexual",
    re.I,
)
DISPUTE = re.compile(
    r"(wrong|missing|incorrect|underpaid|not paid|didn.t (get|receive)).{0,40}(pay|salary|payslip)|"
    r"(pay|salary|payslip).{0,40}(wrong|missing|incorrect)",
    re.I,
)
BALANCE = re.compile(
    r"(remaining|left|balance|still have|have i (used|taken)).{0,40}(vacation|holiday|pto|days off)|"
    r"(vacation|holiday|pto|days off).{0,40}(left|remaining|balance|still have|do i have)",
    re.I,
)
ACTION = re.compile(
    r"^(hi[,!]?\s+)?((can|could|would|will) you\s+(please\s+)?|please\s+)?"
    r"(book|order|buy|cancel|approve|reserve|schedule|transfer|pay me|send me|sign)\b",
    re.I,
)
MANAGER = re.compile(r"who is my (manager|boss|lead)|my (manager|line manager)('s)? name", re.I)
NAME = r"(?-i:[A-ZÄÖÜÁÉÍÓÚ][a-zäöüßáéíóúàèìòùãõçñ]+)"  # a capitalised word: someone's name
NOT_NAME = r"(?!(?-i:My|I|What|When|How|Is|Can|Do|Does|Who|Where|Why|The|Our|HiBob)\b)"
OTHERS_PAY = re.compile(
    rf"\b(salary|earn|earns|paid|pay|compensation|bonus|vacation balance)\b.{{0,30}}\b(of|does|for)\s+{NOT_NAME}{NAME}"
    rf"|\b{NOT_NAME}{NAME}('s|s)?\s+(salary|pay|bonus|compensation)\b"
    rf"|\bwhat does\s+{NOT_NAME}{NAME}.{{0,20}}\bearn"
    r"|(colleague|coworker|co-worker|team ?mate|manager|boss|everyone|team|others)('s|s)?\s+.{0,20}"
    r"(salary|salaries|earn|pay|bonus)"
    rf"|\b(does|do|has|have|did)\s+(my\s+|our\s+|the\s+)?(manager|boss|colleagues?|coworkers?|team ?mates?|"
    rf"team|lead|{NOT_NAME}{NAME})\b.{{0,30}}\b(left|remaining|balance|earn|earns|salary|paid|bonus)\b"
    r"|\b(salary|salaries|pay|earnings|bonus|bonuses|vacation balance|days left)\b.{0,30}"
    r"\b(colleagues?|coworkers?|team ?mates?|everyone|my team|the team|others|other people|my manager|my boss)\b",
    re.I,
)


QUERY_ONLY = {"paid": "payday"}  # "get paid" in a question means pay day; "paid out" in the handbook does not


def tokens(text: str, query: bool = False) -> list[str]:
    out = []
    for w in re.findall(r"[a-zA-Zäöüßáéíóúàèìòùãõçñ]+", text.lower()):
        if w in COUNTRIES:
            w = "country"
        w = QUERY_ONLY.get(w, w) if query else w
        w = SYNONYMS.get(w, w)
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = SYNONYMS.get(w[:-1], w[:-1])
        if w not in STOP and len(w) > 1:
            out.append(w)
    return out


@dataclass
class Section:
    id: str
    country: str  # "all" or DE/ES/PT/IT
    title: str
    text: str
    terms: Counter = field(default_factory=Counter)


def load_handbook() -> list[Section]:
    out = []
    for path in sorted(POLICIES.glob("*.md")):
        country = "all" if path.stem == "global" else path.stem.upper()
        for title, sid, body in re.findall(r"^## (.+?) \{#([\w-]+)\}\n(.+?)(?=^## |\Z)", path.read_text(), re.S | re.M):
            asked = " ".join(re.findall(r"^Asked as: (.+)$", body, re.M))  # how people phrase it; not shown
            text = re.sub(r"^Asked as: .+$", "", body, flags=re.M)
            s = Section(sid, country, title.strip(), " ".join(text.split()))
            s.terms = Counter(tokens(title + " " + title + " " + text + " " + asked))
            out.append(s)
    return out


class People(Protocol):
    def profile(self, employee_id: str) -> dict[str, Any] | None: ...
    def balance(self, employee_id: str) -> dict[str, Any] | None: ...


@dataclass
class Answer:
    kind: str  # answer | handoff | refusal
    text: str
    citations: list[str] = field(default_factory=list)
    tool: str | None = None
    reason: str | None = None


class Assistant:
    def __init__(self, people: People, handbook: list[Section] | None = None):
        self.people = people
        self.sections = handbook or load_handbook()
        n = len(self.sections)
        df: Counter = Counter()
        for s in self.sections:
            df.update(set(s.terms))
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.avg = sum(sum(s.terms.values()) for s in self.sections) / n
        self.cfg = policy()["assistant"]

    def _score(self, q: list[str], s: Section) -> float:
        k1, b = 1.2, 0.75
        length = sum(s.terms.values())
        return sum(
            self.idf.get(t, 0) * s.terms[t] * (k1 + 1) / (s.terms[t] + k1 * (1 - b + b * length / self.avg))
            for t in set(q)
            if t in s.terms
        )

    def search(self, question: str, country: str) -> list[tuple[float, Section]]:
        q = tokens(question, query=True)
        scored = [(self._score(q, s), s) for s in self.sections if s.country in ("all", country)]
        return sorted(scored, key=lambda x: -x[0])

    def ask(self, employee_id: str, question: str) -> Answer:
        me = self.people.profile(employee_id)
        if me is None or me.get("status") != "Active":
            return Answer(
                "refusal",
                "I can only help current employees. Please contact the People team.",
                reason="unknown_or_inactive_user",
            )
        if ACTION.search(question.strip()):
            return Answer(
                "handoff",
                "I can't do that for you, but I've passed your request to the People team.",
                reason="action_request",
            )
        if CONCERN.search(question):
            return Answer(
                "handoff",
                "This is something a person should handle. I have passed it to your People "
                "partner confidentially; you can also use the whistleblowing channel.",
                ["global#concerns"],
                reason="concern",
            )
        if DISPUTE.search(question):
            return Answer(
                "handoff",
                "A person in the People team will look at your pay. Raise it before the 5th "
                "so a correction can go into the next run.",
                ["global#payday"],
                reason="pay_dispute",
            )
        if OTHERS_PAY.search(question):
            return Answer(
                "refusal",
                "I can't share anyone else's pay or personal data. I can help with your own "
                "questions or point you to the published pay bands.",
                ["global#salary-review"],
                reason="other_person_data",
            )
        if BALANCE.search(question):
            bal = self.people.balance(employee_id)
            if bal is None:
                return Answer(
                    "handoff", "I can't find your vacation balance; a person will check it.", reason="no_balance"
                )
            sec = f"{me['country'].lower()}#vacation-{me['country'].lower()}"
            return Answer(
                "answer",
                f"You have {bal['balance']:g} of {bal['total']:g} vacation days left this year ({bal['used']:g} used).",
                [sec],
                tool="timeoff_balance",
            )
        if MANAGER.search(question):
            mgr = self.people.profile(me["manager_id"]) if me.get("manager_id") else None
            if not mgr or mgr.get("status") != "Active":
                return Answer(
                    "handoff",
                    "Your manager isn't set correctly in HiBob; I've asked the People team to fix it.",
                    reason="manager_missing",
                )
            return Answer("answer", f"Your manager is {mgr['display_name']}.", tool="manager")
        ranked = self.search(question, me["country"])
        best_score, best = ranked[0]
        q_terms = set(tokens(question, query=True))
        coverage = len(q_terms & set(best.terms)) / max(len(q_terms), 1)
        if best_score < self.cfg["min_score"] or coverage < self.cfg["min_coverage"]:
            return Answer(
                "handoff", "I'm not sure about this one, so I've passed it to the People team.", reason="low_confidence"
            )
        q = set(tokens(question))
        sentences = re.split(r"(?<=[.!?])\s+", best.text)
        top = sorted(sentences, key=lambda s: -len(q & set(tokens(s))))[:2]
        text = " ".join(s for s in sentences if s in top)  # keep the handbook's own order
        return Answer("answer", text, [f"{best.country.lower() if best.country != 'all' else 'global'}#{best.id}"])
