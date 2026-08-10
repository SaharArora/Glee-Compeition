# GLEE Repository Audit

GLEE root: `work/GLEE`

## Source Files Checked

- `games/base_game.py`: present (file)
- `games/bargaining/bargaining.py`: present (file)
- `games/negotiation/negotiation.py`: present (file)
- `games/persuasion/persuasion.py`: present (file)
- `players/base_player.py`: present (file)
- `players/http_player.py`: present (file)
- `utils/utils.py`: present (file)
- `sample_configs/bargaining/terminal_config.json`: present (file)
- `sample_configs/negotiation/terminal_config.json`: present (file)
- `sample_configs/persuasion/terminal_config.json`: present (file)
- `Data/llm_vs_llm`: present (directory)
- `Data/human_vs_llm`: present (directory)

## Game Mechanics Summary

### Bargaining

- Source: `games/bargaining/bargaining.py`.
- Roles: player 1 and player 2, with alternating proposer/receiver turns by round parity.
- Configuration: `money_to_divide`, `max_rounds`, `complete_information`, `messages_allowed`, `delta_1`, `delta_2`.
- Valid offer: JSON gains for both players summing to `money_to_divide`, plus optional `message`.
- Valid decision: JSON `decision` equal to `accept` or `reject`.
- Termination: first acceptance or exhaustion of `max_rounds`.
- Logged data: `game.csv` alternates offer rows containing `alice_gain`/`bob_gain` and decision rows containing `decision`.
- Payoff reconstruction in this harness follows `analyze/metrics.py`: accepted shares discounted by each player's delta to the agreement round; otherwise zero.

### Negotiation

- Source: `games/negotiation/negotiation.py`.
- Roles: player 1 is seller, player 2 is buyer.
- Configuration: `seller_value`, `buyer_value`, `product_price_order`, `max_rounds`, `complete_information`, `messages_allowed`.
- Valid offer: JSON `product_price`, plus optional `message`.
- Valid decision: JSON `decision` in `AcceptOffer`, `RejectOffer`, `SellToJhon`, `BuyFromJhon`, or legacy `DealWithJhon`.
- Termination: accepted offer, external John option, final rejection, or exhaustion of `max_rounds`.
- Logged data: `game.csv` alternates offer rows containing `product_price` and decision rows containing `decision`.
- Payoff reconstruction follows `analyze/metrics.py`: seller surplus is normalized price minus seller value, buyer surplus is buyer value minus normalized price when trade is accepted; otherwise zero.

### Persuasion

- Source: `games/persuasion/persuasion.py`.
- Roles: player 1 is seller, player 2 is buyer, with Nature logging product quality.
- Configuration: `p`, `v`, `c`, `product_price`, `total_rounds`, `is_seller_know_cv`, `is_buyer_know_p`, `seller_message_type`, `is_myopic`, `allow_buyer_message`.
- Valid seller action: JSON `message` for text mode or `decision` yes/no for binary mode.
- Valid buyer action: JSON `decision` yes/no, plus optional `message` if allowed.
- Termination: fixed number of rounds.
- Logged data: `game.csv` contains Nature quality rows, seller message/recommendation rows, and buyer purchase-decision rows.
- Payoff reconstruction in this harness normalizes seller revenue and buyer realized surplus by `product_price * total_rounds`; audit follow-up should reconcile this with all paper metrics in `analyze/metrics.py`.

## Released Data Counts

- `llm_vs_llm/bargaining`: 32043 complete game directories
- `llm_vs_llm/negotiation`: 32403 complete game directories
- `llm_vs_llm/persuasion`: 13021 complete game directories
- `human_vs_llm/bargaining`: 1696 complete game directories
- `human_vs_llm/negotiation`: 1224 complete game directories
- `human_vs_llm/persuasion`: 485 complete game directories

## Open Details

- Exact counterfactual reference policies remain family-specific research assumptions.
- Persuasion payoff conventions differ depending on whether the target is realized surplus, paper fairness/efficiency metrics, or raw seller revenue.
- The first harness implementation wraps released logs directly and uses a deterministic local simulator for synthetic tournaments; deeper direct execution through upstream game classes should remain an adapter-level extension.
