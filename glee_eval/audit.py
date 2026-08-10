from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from glee_eval.config import DEFAULT_DOCS_DIR, DEFAULT_GLEE_ROOT
from glee_eval.storage.trajectories import write_json


AUDIT_FILES = [
    "games/base_game.py",
    "games/bargaining/bargaining.py",
    "games/negotiation/negotiation.py",
    "games/persuasion/persuasion.py",
    "players/base_player.py",
    "players/http_player.py",
    "utils/utils.py",
    "sample_configs/bargaining/terminal_config.json",
    "sample_configs/negotiation/terminal_config.json",
    "sample_configs/persuasion/terminal_config.json",
    "Data/llm_vs_llm",
    "Data/human_vs_llm",
]


def inspect_repo(glee_root: str | Path = DEFAULT_GLEE_ROOT) -> dict[str, Any]:
    root = Path(glee_root)
    files = {}
    for rel in AUDIT_FILES:
        path = root / rel
        files[rel] = {"exists": path.exists(), "is_dir": path.is_dir() if path.exists() else False}
    sample_counts: dict[str, int] = {}
    data_root = root / "Data"
    for source in ["llm_vs_llm", "human_vs_llm"]:
        for family in ["bargaining", "negotiation", "persuasion"]:
            family_root = data_root / source / family
            count = 0
            if family_root.exists():
                for path in family_root.rglob("config.json"):
                    if (path.parent / "game.csv").exists():
                        count += 1
            sample_counts[f"{source}/{family}"] = count
    return {"glee_root": str(root), "files": files, "game_counts": sample_counts}


def generate_audit_markdown(glee_root: str | Path = DEFAULT_GLEE_ROOT) -> str:
    repo = inspect_repo(glee_root)
    lines = [
        "# GLEE Repository Audit",
        "",
        f"GLEE root: `{repo['glee_root']}`",
        "",
        "## Source Files Checked",
        "",
    ]
    for rel, meta in repo["files"].items():
        status = "present" if meta["exists"] else "missing"
        kind = "directory" if meta.get("is_dir") else "file"
        lines.append(f"- `{rel}`: {status} ({kind})")
    lines += [
        "",
        "## Game Mechanics Summary",
        "",
        "### Bargaining",
        "",
        "- Source: `games/bargaining/bargaining.py`.",
        "- Roles: player 1 and player 2, with alternating proposer/receiver turns by round parity.",
        "- Configuration: `money_to_divide`, `max_rounds`, `complete_information`, `messages_allowed`, `delta_1`, `delta_2`.",
        "- Valid offer: JSON gains for both players summing to `money_to_divide`, plus optional `message`.",
        "- Valid decision: JSON `decision` equal to `accept` or `reject`.",
        "- Termination: first acceptance or exhaustion of `max_rounds`.",
        "- Logged data: `game.csv` alternates offer rows containing `alice_gain`/`bob_gain` and decision rows containing `decision`.",
        "- Payoff reconstruction in this harness follows `analyze/metrics.py`: accepted shares discounted by each player's delta to the agreement round; otherwise zero.",
        "",
        "### Negotiation",
        "",
        "- Source: `games/negotiation/negotiation.py`.",
        "- Roles: player 1 is seller, player 2 is buyer.",
        "- Configuration: `seller_value`, `buyer_value`, `product_price_order`, `max_rounds`, `complete_information`, `messages_allowed`.",
        "- Valid offer: JSON `product_price`, plus optional `message`.",
        "- Valid decision: JSON `decision` in `AcceptOffer`, `RejectOffer`, `SellToJhon`, `BuyFromJhon`, or legacy `DealWithJhon`.",
        "- Termination: accepted offer, external John option, final rejection, or exhaustion of `max_rounds`.",
        "- Logged data: `game.csv` alternates offer rows containing `product_price` and decision rows containing `decision`.",
        "- Payoff reconstruction follows `analyze/metrics.py`: seller surplus is normalized price minus seller value, buyer surplus is buyer value minus normalized price when trade is accepted; otherwise zero.",
        "",
        "### Persuasion",
        "",
        "- Source: `games/persuasion/persuasion.py`.",
        "- Roles: player 1 is seller, player 2 is buyer, with Nature logging product quality.",
        "- Configuration: `p`, `v`, `c`, `product_price`, `total_rounds`, `is_seller_know_cv`, `is_buyer_know_p`, `seller_message_type`, `is_myopic`, `allow_buyer_message`.",
        "- Valid seller action: JSON `message` for text mode or `decision` yes/no for binary mode.",
        "- Valid buyer action: JSON `decision` yes/no, plus optional `message` if allowed.",
        "- Termination: fixed number of rounds.",
        "- Logged data: `game.csv` contains Nature quality rows, seller message/recommendation rows, and buyer purchase-decision rows.",
        "- Payoff reconstruction in this harness normalizes seller revenue and buyer realized surplus by `product_price * total_rounds`; audit follow-up should reconcile this with all paper metrics in `analyze/metrics.py`.",
        "",
        "## Released Data Counts",
        "",
    ]
    for key, count in repo["game_counts"].items():
        lines.append(f"- `{key}`: {count} complete game directories")
    lines += [
        "",
        "## Open Details",
        "",
        "- Exact counterfactual reference policies remain family-specific research assumptions.",
        "- Persuasion payoff conventions differ depending on whether the target is realized surplus, paper fairness/efficiency metrics, or raw seller revenue.",
        "- The first harness implementation wraps released logs directly and uses a deterministic local simulator for synthetic tournaments; deeper direct execution through upstream game classes should remain an adapter-level extension.",
        "",
    ]
    return "\n".join(lines)


def write_audit(glee_root: str | Path = DEFAULT_GLEE_ROOT, docs_dir: str | Path = DEFAULT_DOCS_DIR) -> Path:
    docs = Path(docs_dir)
    docs.mkdir(parents=True, exist_ok=True)
    markdown = generate_audit_markdown(glee_root)
    path = docs / "GLEE_AUDIT.md"
    path.write_text(markdown, encoding="utf-8")
    write_json(Path("reports") / "glee_audit.json", inspect_repo(glee_root))
    return path


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Create docs/GLEE_AUDIT.md from the local GLEE checkout.")
    parser.add_argument("--glee-root", default=str(DEFAULT_GLEE_ROOT))
    parser.add_argument("--docs-dir", default=str(DEFAULT_DOCS_DIR))
    args = parser.parse_args(argv)
    print(write_audit(args.glee_root, args.docs_dir))


if __name__ == "__main__":
    main()

