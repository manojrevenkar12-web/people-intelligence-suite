"""Read People data from HiBob the way HiBob recommends for whole-company reads.

1. Discover IDs with a light search (`fields: ["root.id"]`, `showInactive: true` to include leavers).
2. Read the fields in batches of IDs (HiBob allows up to 200 values per filter; we use 100).
3. Read effective-dated tables (salaries, work history) through the paginated bulk endpoints.

Responses come back with slash keys (`/work/department`); this client maps them back to dot IDs.
A field the service user cannot read is absent, not an error, so the client checks that every
requested field arrived and reports the ones that did not: a silent gap is the failure that matters.
429 answers are retried after Retry-After.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx

PEOPLE_FIELDS = [
    "root.id",
    "root.displayName",
    "root.email",
    "work.department",
    "work.title",
    "work.site",
    "work.startDate",
    "work.reportsTo",
    "work.customColumns.level",
    "internal.status",
    "internal.terminationDate",
    "internal.terminationReason",
    "payroll.employment.type",
    "payroll.employment.weeklyHours",
    "payroll.employment.country",
]


@dataclass
class ReadReport:
    requests: int = 0
    retries: int = 0
    missing_fields: dict[str, int] = field(default_factory=dict)


class HiBobClient:
    def __init__(
        self,
        base_url: str,
        user: str,
        token: str,
        http: httpx.Client | None = None,
        batch: int = 100,
        max_retries: int = 5,
        sleep=time.sleep,
    ):  # type: ignore[no-untyped-def]
        auth = "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()
        self.http = http or httpx.Client(base_url=base_url, timeout=30)
        self.http.headers["Authorization"] = auth
        self.batch, self.max_retries, self.sleep = batch, max_retries, sleep
        self.report = ReadReport()

    def _call(self, method: str, url: str, **kw: Any) -> Any:
        for attempt in range(self.max_retries + 1):
            self.report.requests += 1
            r = self.http.request(method, url, **kw)
            if r.status_code == 429 and attempt < self.max_retries:
                self.report.retries += 1
                self.sleep(float(r.headers.get("Retry-After", "1")))
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError("unreachable")

    def employee_ids(self, include_inactive: bool = True) -> list[str]:
        body = {"fields": ["root.id"], "showInactive": include_inactive}
        return [e["/root/id"]["value"] for e in self._call("POST", "/v1/people/search", json=body)["employees"]]

    def people(self, fields: list[str] | None = None, include_inactive: bool = True) -> list[dict[str, Any]]:
        fields = fields or PEOPLE_FIELDS
        ids = self.employee_ids(include_inactive)
        out = []
        for i in range(0, len(ids), self.batch):
            body = {
                "fields": fields,
                "showInactive": include_inactive,
                "filters": [{"fieldPath": "root.id", "operator": "equals", "values": ids[i : i + self.batch]}],
            }
            for e in self._call("POST", "/v1/people/search", json=body)["employees"]:
                row = {k[1:].replace("/", "."): v["value"] for k, v in e.items() if k.startswith("/")}
                for f in fields:
                    if f not in row:
                        self.report.missing_fields[f] = self.report.missing_fields.get(f, 0) + 1
                out.append(row)
        return out

    def table(self, name: str, limit: int = 200) -> Iterator[dict[str, Any]]:
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": limit}
            if cursor:
                params["cursor"] = cursor
            page = self._call("GET", f"/v1/bulk/people/{name}", params=params)
            yield from page["results"]
            cursor = page["response_metadata"]["next_cursor"]
            if not cursor:
                return

    def timeoff_balance(self, employee_id: str, policy: str = "Holiday") -> dict[str, Any]:
        return self._call("GET", f"/v1/timeoff/employees/{employee_id}/balance", params={"policyType": policy})
