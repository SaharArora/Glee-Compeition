from __future__ import annotations

import argparse

from glee_eval.audit import main as audit_main
from glee_eval.data.dataset_audit import main as dataset_audit_main
from glee_eval.data.ingest import main as ingest_main
from glee_eval.data.stats import main as stats_main
from glee_eval.data.validation import main as validate_main
from glee_eval.experiments.run import main as experiment_main
from glee_eval.population.calibration import main as calibrate_main
from glee_eval.probes.runner import main as probes_main
from glee_eval.response_models.train import main as train_response_models_main
from glee_eval.scoring.shadow import main as shadow_score_main
from glee_eval.search.adversarial import main as search_main
from glee_eval.tournament.runner import main as tournament_main


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="GLEE local evaluation harness")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in [
        "audit",
        "dataset-audit",
        "ingest",
        "validate",
        "stats",
        "probes",
        "train-response-models",
        "tournament",
        "experiment",
        "calibrate-population",
        "search-failures",
        "shadow-score",
    ]:
        sub.add_parser(name)
    args, rest = parser.parse_known_args(argv)
    if args.command == "audit":
        audit_main(rest)
    elif args.command == "dataset-audit":
        dataset_audit_main(rest)
    elif args.command == "ingest":
        ingest_main(rest)
    elif args.command == "validate":
        validate_main(rest)
    elif args.command == "stats":
        stats_main(rest)
    elif args.command == "probes":
        probes_main(rest)
    elif args.command == "train-response-models":
        train_response_models_main(rest)
    elif args.command == "tournament":
        tournament_main(rest)
    elif args.command == "experiment":
        experiment_main(rest)
    elif args.command == "calibrate-population":
        calibrate_main(rest)
    elif args.command == "search-failures":
        search_main(rest)
    elif args.command == "shadow-score":
        shadow_score_main(rest)
    else:  # pragma: no cover
        parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
