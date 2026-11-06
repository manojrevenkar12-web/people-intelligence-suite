"""The simulated company: Jimdo-sized, remote-first, in Germany, Spain, Portugal and Italy.

Writes what the People team's systems would hold (HiBob, two payroll vendors, the compensation tool,
Finance's general ledger) into `data/sources/`, with the mistakes real systems make, and writes the
answer key into `data/truth/`. Nothing outside `pis.sim` and `pis.evaluate` may read the truth.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[3]

FIRST = {
    "DE": (
        ["Lena", "Anna", "Marie", "Julia", "Laura", "Sophie", "Lea", "Hannah", "Katrin", "Nina"],
        ["Jonas", "Lukas", "Felix", "Paul", "Max", "Tim", "Jan", "Niklas", "Moritz", "Tobias"],
    ),
    "ES": (
        ["Lucía", "María", "Paula", "Carmen", "Sara", "Elena", "Marta", "Irene"],
        ["Hugo", "Pablo", "Daniel", "Alejandro", "Javier", "Diego", "Sergio", "Álvaro"],
    ),
    "PT": (
        ["Beatriz", "Inês", "Mariana", "Ana", "Joana", "Rita", "Catarina", "Sofia"],
        ["João", "Rodrigo", "Tiago", "Duarte", "Miguel", "Pedro", "Rui", "Nuno"],
    ),
    "IT": (
        ["Giulia", "Chiara", "Francesca", "Sara", "Martina", "Elisa", "Valentina", "Alessia"],
        ["Luca", "Marco", "Matteo", "Andrea", "Lorenzo", "Davide", "Simone", "Federico"],
    ),
}
LAST = {
    "DE": [
        "Schmidt",
        "Fischer",
        "Weber",
        "Wagner",
        "Becker",
        "Hoffmann",
        "Koch",
        "Richter",
        "Klein",
        "Wolf",
        "Neumann",
        "Schwarz",
        "Krüger",
        "Hartmann",
        "Lange",
    ],
    "ES": ["García", "Martínez", "López", "Sánchez", "Romero", "Navarro", "Torres", "Ruiz", "Moreno", "Ortega"],
    "PT": ["Silva", "Santos", "Ferreira", "Pereira", "Costa", "Oliveira", "Rodrigues", "Martins", "Sousa", "Lopes"],
    "IT": ["Rossi", "Russo", "Ferrari", "Esposito", "Bianchi", "Romano", "Colombo", "Ricci", "Marino", "Greco"],
}
TITLES = {
    "Engineering": ["Software Engineer", "Backend Engineer", "Frontend Engineer", "Engineering Manager"],
    "Product": ["Product Manager", "Product Owner", "Group Product Manager"],
    "Design": ["Product Designer", "UX Researcher", "Design Lead"],
    "Marketing": ["Marketing Manager", "Content Marketer", "Growth Marketer"],
    "Customer Success": ["Customer Success Agent", "Support Specialist", "Customer Success Lead"],
    "Sales": ["Account Executive", "Partnerships Manager", "Sales Lead"],
    "Finance": ["Financial Analyst", "Accountant", "Finance Manager"],
    "People": ["People Partner", "People Operations Specialist", "Talent Partner"],
    "Data & Analytics": ["Data Analyst", "Analytics Engineer", "Data Scientist"],
}
LEVELS = ["L1", "L2", "L3", "L4", "L5", "L6"]
ENTITLEMENT = {"DE": 30, "ES": 23, "PT": 22, "IT": 26}  # matches the handbook in pis/assistant/policies
ASCII = str.maketrans("äöüßáéíóúàèìòùãõçñ", "aousaeiouaeiouaocn")


def load_company() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "config" / "company.yaml").read_text())


def month_range(end: str, n: int) -> list[date]:
    y, m = map(int, end.split("-"))
    out = []
    for _ in range(n):
        out.append(date(y, m, 1))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


def month_end(d: date) -> date:
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def next_month(d: date) -> date:
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


@dataclass
class Person:
    id: str
    first: str
    surname: str
    email: str
    gender: str
    birth: date
    country: str
    department: str
    level: str
    title: str
    start: date
    hours: int = 40
    end: date | None = None
    reason: str | None = None
    reports_to: str | None = None
    salary: list[tuple[date, float]] = field(default_factory=list)  # (effective, annual base EUR)
    work: list[tuple[date, str, str, str]] = field(default_factory=list)  # (effective, department, title, level)

    def base_on(self, d: date) -> float:
        val = self.salary[0][1]
        for eff, v in self.salary:
            if eff <= d:
                val = v
        return val

    def department_on(self, d: date) -> str:
        val = self.work[0][1]
        for eff, dep, _, _ in self.work:
            if eff <= d:
                val = dep
        return val

    def active_in(self, m: date) -> bool:
        return self.start <= month_end(m) and (self.end is None or self.end >= m)


class Company:
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.rng = np.random.default_rng(cfg["seed"])
        self.months = month_range(cfg["end_month"], cfg["months"])
        self.people: dict[str, Person] = {}
        self.emails: set[str] = set()
        self.truth: dict[str, list[dict[str, Any]]] = {}

    def _id(self) -> str:
        return str(int(self.rng.integers(10**18, 9 * 10**18)))

    def _pick(self, weights: dict[str, float]) -> str:
        keys = list(weights)
        p = np.array([weights[k] for k in keys], float)
        return keys[int(self.rng.choice(len(keys), p=p / p.sum()))]

    def _band(self, country: str, dept: str, level: str) -> float:
        c = self.cfg
        return c["band_mid_de"][level] * c["country_factor"][country] * c["department_factor"][dept]

    # ----------------------------------------------------------------------------------- people
    def new_person(self, start: date, level: str | None = None, dept: str | None = None) -> Person:
        c = self.cfg
        country = self._pick({k: v["share"] for k, v in c["countries"].items()})
        dept = dept or self._pick(c["departments"])
        level = level or self._pick(c["levels"])
        u = self.rng.random()
        if u < c["female_share"]:
            gender, firsts = "female", FIRST[country][0]
        elif u < c["female_share"] + c["nonbinary_share"]:
            gender, firsts = "non-binary", FIRST[country][0] + FIRST[country][1]
        else:
            gender, firsts = "male", FIRST[country][1]
        first = str(self.rng.choice(firsts))
        surname = str(self.rng.choice(LAST[country]))
        stem = f"{first.lower()}.{surname.lower()}".translate(ASCII)
        email, k = f"{stem}@example-company.com", 2
        while email in self.emails:
            email, k = f"{stem}{k}@example-company.com", k + 1
        self.emails.add(email)
        title = str(self.rng.choice(TITLES[dept]))
        hours = int(self.rng.choice([20, 24, 30, 32])) if self.rng.random() < c["part_time_share"] else 40
        birth = date(int(self.rng.integers(1965, 2002)), int(self.rng.integers(1, 13)), int(self.rng.integers(1, 28)))
        p = Person(self._id(), first, surname, email, gender, birth, country, dept, level, title, start, hours)
        base = self._band(country, dept, level) * float(np.exp(self.rng.normal(0, 0.06)))
        gap = c["planted_gap"]
        if gender == "female" and dept == gap["department"]:
            base *= 1 - gap["female_discount"]
        p.salary.append((start, round(base, -2)))
        p.work.append((start, dept, title, level))
        self.people[p.id] = p
        return p

    def build(self) -> None:
        c = self.cfg
        first_month = self.months[0]
        for _ in range(c["headcount_start"]):
            self.new_person(first_month - timedelta(days=int(self.rng.integers(30, 8 * 365))))
        self.ceo = self.new_person(date(2013, 1, 1), level="L6", dept="Product")
        self.ceo.title = "Chief Executive Officer"
        self.ceo.work[0] = (self.ceo.start, "Product", self.ceo.title, "L6")
        for m in self.months:
            active = [p for p in self.people.values() if p.active_in(m) and p is not self.ceo]
            for p in active:  # leavers
                if p.end is None and p.start < m and self.rng.random() < c["monthly_leave_rate"]:
                    p.end = month_end(m) - timedelta(days=int(self.rng.integers(0, 20)))
                    p.reason = "voluntary" if self.rng.random() < c["voluntary_share"] else "involuntary"
            for _ in range(int(self.rng.poisson(c["monthly_hire_rate"] * len(active)))):  # hires
                self.new_person(m + timedelta(days=int(self.rng.integers(0, 3)) * 7))
            if m.month == c["review_month"]:  # merit review and promotions
                for p in active:
                    if p.end is not None and p.end < m or p.start >= m:
                        continue
                    base = p.base_on(m)
                    lvl = p.work[-1][3]
                    if self.rng.random() < c["promotion_rate"] and lvl != "L6":
                        new_lvl = LEVELS[LEVELS.index(lvl) + 1]
                        p.work.append((m, p.work[-1][1], p.work[-1][2], new_lvl))
                        p.level = new_lvl
                        base = max(base * 1.08, self._band(p.country, p.work[-1][1], new_lvl) * 0.9)
                    p.salary.append((m, round(base * (1 + max(0.0, self.rng.normal(c["merit_mean"], 0.015))), -2)))
            if self.rng.random() < 0.35:  # an internal transfer
                movers = [
                    p for p in active if p.end is None and p.start < m - timedelta(days=200) and p.work[-1][0] < m
                ]
                if movers:
                    p = movers[int(self.rng.integers(len(movers)))]
                    new_dept = self._pick({k: v for k, v in c["departments"].items() if k != p.work[-1][1]})
                    p.work.append((m, new_dept, str(self.rng.choice(TITLES[new_dept])), p.work[-1][3]))
                    p.department = new_dept
        self._assign_managers()

    def _assign_managers(self) -> None:
        end = month_end(self.months[-1])
        for p in self.people.values():
            if p is self.ceo:
                continue
            dept = p.department_on(end if p.end is None else p.end)
            mine = LEVELS.index(p.work[-1][3])
            peers = [
                q
                for q in self.people.values()
                if q is not p
                and q is not self.ceo
                and q.end is None
                and q.department_on(end) == dept
                and LEVELS.index(q.work[-1][3]) > mine
            ]
            if not peers:
                p.reports_to = self.ceo.id
                continue
            near = min(LEVELS.index(q.work[-1][3]) for q in peers)
            pool = [q for q in peers if LEVELS.index(q.work[-1][3]) <= near + 1]
            p.reports_to = pool[int(self.rng.integers(len(pool)))].id

    # ----------------------------------------------------------------------------------- defects
    def plant(self) -> None:
        d = self.cfg["defects"]
        rng = self.rng
        last = self.months[-1]
        T = self.truth

        def choose(pool: list[Person], n: int) -> list[Person]:
            pool = sorted(pool, key=lambda p: p.id)
            idx = rng.choice(len(pool), size=min(n, len(pool)), replace=False)
            return [pool[int(i)] for i in idx]

        leavers = [p for p in self.people.values() if p.end and p.end < last and p.end >= self.months[1]]
        self.paid_after = {
            p.id: next_month(date(p.end.year, p.end.month, 1)) for p in choose(leavers, d["leaver_paid"])
        }
        T["leaver_paid"] = [{"employee_id": k, "month": v.isoformat()[:7]} for k, v in self.paid_after.items()]

        joiners = [p for p in self.people.values() if p.start >= self.months[1] and p.end is None]
        self.joiner_missing = {p.id: date(p.start.year, p.start.month, 1) for p in choose(joiners, d["joiner_missing"])}
        T["joiner_missing"] = [{"employee_id": k, "month": v.isoformat()[:7]} for k, v in self.joiner_missing.items()]

        changed = [
            p
            for p in self.people.values()
            if len(p.salary) > 1
            and p.id not in self.paid_after
            and p.salary[-1][0] >= self.months[0]
            and (p.end is None or p.end >= p.salary[-1][0])
        ]
        self.raise_missing: dict[str, tuple[date, float]] = {}
        for p in choose(changed, d["raise_not_in_payroll"]):
            self.raise_missing[p.id] = (p.salary[-1][0], p.salary[-2][1])
        T["raise_not_in_payroll"] = [
            {"employee_id": k, "from_month": v[0].isoformat()[:7]} for k, v in self.raise_missing.items()
        ]

        part = [
            p
            for p in self.people.values()
            if p.hours < 40
            and p.id not in self.raise_missing
            and p.id not in self.paid_after
            and p.id not in self.joiner_missing
        ]
        self.fte_wrong = {p.id for p in choose(part, d["fte_mismatch"])}
        T["fte_mismatch"] = [{"employee_id": k} for k in self.fte_wrong]

        mgr_ids = {p.reports_to for p in self.people.values() if p.reports_to}
        gone = sorted([q for q in self.people.values() if q.end and q.id not in mgr_ids], key=lambda q: q.id)
        actives = [p for p in self.people.values() if p.end is None and p is not self.ceo]
        T["manager_is_leaver"] = []
        for p in choose(actives, d["manager_is_leaver"]):
            p.reports_to = gone[int(rng.integers(len(gone)))].id
            T["manager_is_leaver"].append({"employee_id": p.id})
        taken = {x["employee_id"] for x in T["manager_is_leaver"]}
        T["missing_manager"] = []
        for p in choose([p for p in actives if p.id not in taken], d["missing_manager"]):
            p.reports_to = None
            T["missing_manager"].append({"employee_id": p.id})

        T["duplicate_rehire"] = []
        old = [p for p in self.people.values() if p.end and p.end < self.months[-6]]
        for p in choose(old, d["duplicate_rehire"]):
            q = Person(
                self._id(),
                p.first,
                p.surname,
                p.email.replace("@", ".rehire@"),
                p.gender,
                p.birth,
                p.country,
                p.department,
                p.level,
                p.title,
                self.months[-3] + timedelta(days=14),
                p.hours,
            )
            q.salary = [(q.start, p.salary[-1][1])]
            q.work = [(q.start, p.department, p.title, p.level)]
            q.reports_to = self.ceo.id
            self.people[q.id] = q
            T["duplicate_rehire"].append({"employee_id": q.id, "same_as": p.id})

        moved = [
            p
            for p in self.people.values()
            if len({w[1] for w in p.work}) > 1
            and p.end is None
            and p.id not in self.raise_missing
            and p.id not in self.fte_wrong
        ]
        self.gl_old: dict[str, tuple[date, str]] = {}
        for p in choose(moved, d["gl_old_cost_center"]):
            last_move = max(i for i, w in enumerate(p.work) if w[1] != p.work[i - 1][1]) if len(p.work) > 1 else 1
            self.gl_old[p.id] = (p.work[last_move][0], p.work[last_move - 1][1])
        T["gl_old_cost_center"] = [
            {"employee_id": k, "from_month": v[0].isoformat()[:7], "old_department": v[1]}
            for k, v in self.gl_old.items()
        ]
        # approved in the compensation tool, never entered in HiBob (so payroll never paid it either)
        self.cycle = max(m for m in self.months if m.month == self.cfg["review_month"])
        reviewed = [
            p
            for p in self.people.values()
            if p.end is None
            and p.id not in self.raise_missing
            and p.id not in self.gl_old
            and any(e == self.cycle for e, _ in p.salary)
        ]
        self.comp_missing: dict[str, float] = {}
        for p in choose(reviewed, d["comp_not_in_hibob"]):
            self.comp_missing[p.id] = next(v for e, v in p.salary if e == self.cycle)
            p.salary = [(e, v) for e, v in p.salary if e != self.cycle]
        T["comp_not_in_hibob"] = [{"employee_id": k} for k in self.comp_missing]
        self.cents = (self.months[-8].isoformat()[:7], "IT")
        T["vendor_cents_month"] = [{"vendor": "cloudpay", "country": "IT", "month": self.cents[0]}]

    # ----------------------------------------------------------------------------------- payroll
    def payroll_rows(self) -> list[dict[str, Any]]:
        rate = {k: v["employer_rate"] for k, v in self.cfg["countries"].items()}
        rows = []
        for m in self.months:
            me = month_end(m)
            for p in self.people.values():
                extra = self.paid_after.get(p.id) == m
                if (not p.active_in(m) and not extra) or self.joiner_missing.get(p.id) == m:
                    continue
                if extra:
                    frac = 1.0
                else:
                    a, b = max(p.start, m), min(p.end or me, me)
                    frac = ((b - a).days + 1) / ((me - m).days + 1)
                base = p.base_on(me)
                if p.id in self.raise_missing and m >= self.raise_missing[p.id][0]:
                    base = self.raise_missing[p.id][1]
                hours = 40 if p.id in self.fte_wrong else p.hours
                monthly = base / 12 * hours / 40
                gross = round(monthly * frac, 2)
                dept = p.department_on(me) if not extra else p.department_on(p.end)
                gl_dept = self.gl_old[p.id][1] if p.id in self.gl_old and m >= self.gl_old[p.id][0] else dept
                rows.append(
                    {
                        "month": m.isoformat()[:7],
                        "employee_id": p.id,
                        "country": p.country,
                        "department": dept,
                        "gl_department": gl_dept,
                        "weekly_hours": hours,
                        "base_monthly": round(monthly, 2),
                        "gross": gross,
                        "employer_cost": round(gross * (1 + rate[p.country]), 2),
                    }
                )
        return rows

    # ----------------------------------------------------------------------------------- writers
    def write(self, out: Path) -> dict[str, Any]:
        src, truth = out / "sources", out / "truth"
        for d in ("hibob", "payroll", "finance", "comp"):
            (src / d).mkdir(parents=True, exist_ok=True)
        truth.mkdir(parents=True, exist_ok=True)
        last = month_end(self.months[-1])
        people = []
        for p in self.people.values():
            status = "Active" if p.end is None or p.end >= last else "Inactive"
            people.append(
                {
                    "id": p.id,
                    "firstName": p.first,
                    "surname": p.surname,
                    "displayName": f"{p.first} {p.surname}",
                    "email": p.email,
                    "work": {
                        "department": p.department_on(last if p.end is None else p.end),
                        "title": p.work[-1][2],
                        "site": self.cfg["countries"][p.country]["site"],
                        "startDate": p.start.isoformat(),
                        "reportsTo": {"id": p.reports_to} if p.reports_to else None,
                        "customColumns": {"level": p.work[-1][3]},
                    },
                    "internal": {
                        "status": status,
                        "lifecycleStatus": "employed" if status == "Active" else "terminated",
                        "terminationDate": p.end.isoformat() if p.end else None,
                        "terminationReason": p.reason,
                    },
                    "payroll": {
                        "employment": {
                            "type": "Part time" if p.hours < 40 else "Full time",
                            "weeklyHours": p.hours,
                            "country": p.country,
                        }
                    },
                    "personal": {"gender": p.gender, "birthDate": p.birth.isoformat()},
                }
            )
        (src / "hibob" / "people.json").write_text(json.dumps(people, ensure_ascii=False, indent=0))
        sal = [
            {
                "employeeId": p.id,
                "effectiveDate": e.isoformat(),
                "base": {"value": v, "currency": "EUR"},
                "payPeriod": "Annual",
            }
            for p in self.people.values()
            for e, v in p.salary
        ]
        (src / "hibob" / "salaries.json").write_text(json.dumps(sal, indent=0))
        work = [
            {
                "employeeId": p.id,
                "effectiveDate": e.isoformat(),
                "department": dep,
                "title": t,
                "customColumns": {"level": lv},
            }
            for p in self.people.values()
            for e, dep, t, lv in p.work
        ]
        (src / "hibob" / "work.json").write_text(json.dumps(work, indent=0))
        timeoff = []
        for p in sorted(self.people.values(), key=lambda q: q.id):
            if p.end is not None and p.end < last:
                continue
            ent = ENTITLEMENT[p.country] * p.hours / 40
            used = round(float(self.rng.uniform(0.3, 0.95)) * ent, 1)
            timeoff.append(
                {
                    "employeeId": p.id,
                    "policyType": "Holiday",
                    "year": last.year,
                    "total": round(ent, 1),
                    "used": used,
                    "balance": round(ent - used, 1),
                }
            )
        (src / "hibob" / "timeoff.json").write_text(json.dumps(timeoff, indent=0))

        rows = self.payroll_rows()
        alias = {"Customer Success": "Cust. Success", "Data & Analytics": "Data and Analytics"}
        by_file: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            vendor = self.cfg["countries"][r["country"]]["vendor"]
            key = f"cloudpay_{r['country'].lower()}_{r['month']}" if vendor == "cloudpay" else f"datev_{r['month']}"
            by_file.setdefault(key, []).append(r)
        de = lambda x: f"{x:.2f}".replace(".", ",")  # noqa: E731
        for key, rs in by_file.items():
            path = src / "payroll" / f"{key}.csv"
            with path.open("w", newline="", encoding="utf-8") as f:
                if key.startswith("datev"):
                    w = csv.writer(f, delimiter=";")
                    w.writerow(
                        [
                            "Monat",
                            "Mitarbeiter-ID",
                            "Kostenstelle",
                            "Wochenstunden",
                            "Grundgehalt",
                            "Brutto",
                            "Arbeitgeberkosten",
                        ]
                    )
                    for r in rs:
                        w.writerow(
                            [
                                r["month"],
                                r["employee_id"],
                                r["department"],
                                r["weekly_hours"],
                                de(r["base_monthly"]),
                                de(r["gross"]),
                                de(r["employer_cost"]),
                            ]
                        )
                else:
                    scale = 100 if (rs[0]["month"], rs[0]["country"]) == self.cents else 1
                    w = csv.writer(f)
                    w.writerow(
                        [
                            "pay_period",
                            "employee_ref",
                            "country",
                            "cost_centre",
                            "weekly_hours",
                            "base_monthly",
                            "gross_pay",
                            "employer_cost",
                            "currency",
                        ]
                    )
                    for r in rs:
                        w.writerow(
                            [
                                r["month"],
                                r["employee_id"],
                                r["country"],
                                alias.get(r["department"], r["department"]),
                                r["weekly_hours"],
                                round(r["base_monthly"] * scale, 2),
                                round(r["gross"] * scale, 2),
                                round(r["employer_cost"] * scale, 2),
                                "EUR",
                            ]
                        )
        gl: dict[tuple[str, str, str], float] = {}
        for r in rows:
            k = (r["month"], r["country"], r["gl_department"])
            gl[k] = gl.get(k, 0.0) + r["employer_cost"]
        with (src / "finance" / "gl_personnel.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["period", "entity", "cost_center", "account", "amount_eur"])
            for (mo, ctry, dep), v in sorted(gl.items()):
                w.writerow([mo, f"{ctry}01", dep, "6200", round(v, 2)])

        cycle = self.cycle
        comp = []
        for p in sorted(self.people.values(), key=lambda q: q.id):
            new = self.comp_missing.get(p.id) or next((v for e, v in p.salary if e == cycle), None)
            prev = next((v for e, v in reversed(p.salary) if e < cycle), None)
            if new is not None and prev is not None:
                comp.append(
                    {
                        "employee_id": p.id,
                        "cycle": cycle.isoformat()[:7],
                        "current_base": prev,
                        "approved_base": new,
                        "effective_date": cycle.isoformat(),
                        "status": "approved",
                    }
                )
        with (src / "comp" / "cycle.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(comp[0]))
            w.writeheader()
            w.writerows(comp)
        gap = self.cfg["planted_gap"]
        self.truth["pay_gap"] = [{"department": gap["department"], "female_discount": gap["female_discount"]}]
        (truth / "defects.json").write_text(json.dumps(self.truth, indent=2))
        digest = hashlib.sha256((src / "hibob" / "people.json").read_bytes()).hexdigest()[:12]
        return {"people": len(people), "payroll_rows": len(rows), "files": len(by_file), "digest": digest}


def generate(out: Path | None = None) -> dict[str, Any]:
    c = Company(load_company())
    c.build()
    c.plant()
    return c.write(out or ROOT / "data")
