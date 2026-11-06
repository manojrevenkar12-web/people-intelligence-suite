"""pis simulate | pipeline | evaluate | report | n8n"""

from __future__ import annotations

import argparse
import json


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="pis")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("simulate", help="write the simulated company's sources and truth into data/")
    sub.add_parser("pipeline", help="HiBob and files into landing, through contracts, then dbt build")
    sub.add_parser("evaluate", help="score everything against the truth -> reports/results.json")
    sub.add_parser("report", help="reports/REPORT.md, the dashboard and the Tableau extract")
    sub.add_parser("n8n", help="write the n8n workflows into n8n/workflows/")
    serve = sub.add_parser("serve", help="run the API the n8n workflows call")
    serve.add_argument("--port", type=int, default=8080)
    args = ap.parse_args(argv)
    if args.cmd == "simulate":
        from pis.sim.company import generate

        print(json.dumps(generate(), indent=2))
    elif args.cmd == "pipeline":
        from pis.pipeline import run

        print(json.dumps(run(), indent=2, default=str))
    elif args.cmd == "evaluate":
        from pis.evaluate import evaluate

        r = evaluate()
        print(
            json.dumps({k: v for k, v in r.items() if k in ("data", "pay_gap", "sync", "audit")}, indent=2, default=str)
        )
    elif args.cmd == "report":
        from pis.report import build

        build()
    elif args.cmd == "n8n":
        from pis.n8n_build import build

        for p in build():
            print(p)
    elif args.cmd == "serve":
        import uvicorn

        from pis.api import HiBobPeople, create_app
        from pis.pipeline import hibob_client
        from pis.privacy import AuditLog

        uvicorn.run(create_app(HiBobPeople(hibob_client(), AuditLog())), port=args.port)


if __name__ == "__main__":
    main()
