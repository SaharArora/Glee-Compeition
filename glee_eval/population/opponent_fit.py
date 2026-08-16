"""Fit synthetic-opponent parameters to the real GLEE population.

Two problems this solves at once.

`sample_opponent_spec` drew every behavioral parameter from a hand-picked
`rng.uniform(...)` range that was never checked against data, so every synthetic
tournament measured the agent against invented opponents. And because it always
supplied those parameters, the archetype-specific defaults in `policies.py`
(`_target_share`, `_honesty`, `_trust`) were dead code -- the 16 archetype labels
had no effect on negotiation or persuasion behavior at all, and only a marginal
one on bargaining.

Here an archetype instead names a *band of the observed distribution*: an
`aggressive_extractor` is drawn from the top quantiles of what real players
actually did, a `conceding` opponent from the bottom. That keeps archetypes
meaningful without inventing them, and without building the learned latent-type
model (Model B) that remains deliberately deferred.
"""

from __future__ import annotations

import json
import hashlib
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from math import sqrt
from statistics import mean, pstdev
from typing import Any, Callable, Iterable

from glee_eval.config import DEFAULT_DATA_DIR
from glee_eval.data.ingest import as_float
from glee_eval.data.transcripts import (
    as_dict,
    bargaining_offer_self_share,
    bargaining_share_to_responder,
    last_transcript_action,
    negotiation_normalized_price,
    persuasion_recommendation,
    persuasion_round_quality,
    same_round_transcript_item,
)
from glee_eval.population.splits import DEFAULT_HOLDOUT_FRACTION, add_split_arguments, is_holdout_key, keeps, split_provenance
from glee_eval.population.config_keys import canonical_config, canonical_config_key
from glee_eval.population.crossfit import row_fold
from glee_eval.storage.trajectories import ensure_dir, iter_jsonl, write_json


# Where each archetype sits in the observed behavioral distribution, as a
# quantile window. Wide windows mean a less predictable opponent; `random` spans
# almost the whole range on purpose.
ARCHETYPE_BANDS: dict[str, tuple[float, float]] = {
    "aggressive_extractor": (0.80, 0.98),
    "boulware": (0.75, 0.95),
    "commitment_testing": (0.70, 0.92),
    "deceptive": (0.70, 0.95),
    "level_2": (0.60, 0.85),
    "rational": (0.55, 0.80),
    "adaptive": (0.50, 0.80),
    "historical_imitator": (0.40, 0.60),
    "commitment_respecting": (0.35, 0.60),
    "reciprocal": (0.35, 0.60),
    "level_1": (0.30, 0.55),
    "fairness_sensitive": (0.25, 0.50),
    "myopic": (0.20, 0.50),
    "level_0": (0.10, 0.35),
    "conceding": (0.05, 0.25),
    "random": (0.02, 0.98),
}
DEFAULT_BAND = (0.25, 0.75)

# Parameters where a *higher* observed value means a *softer* opponent, so the
# archetype band has to be read from the other end.
INVERTED_PARAMETERS = {"concession_rate", "accept_margin", "trust_prior"}

_MIN_BUCKET = 25
_QUANTILE_POINTS = tuple(round(0.01 * i, 2) for i in range(1, 100))
_RIDGE_GRID = (0.1, 1.0, 10.0, 100.0)


def _sigmoid(value: float) -> float:
    if value >= 0:
        term = math.exp(-min(value, 40.0))
        return 1.0 / (1.0 + term)
    term = math.exp(max(value, -40.0))
    return term / (1.0 + term)


def _game_fold(game_id: str, folds: int = 3) -> int:
    return int(hashlib.sha256(game_id.encode("utf-8")).hexdigest()[:16], 16) % folds


def _fit_response_coefficients(
    rows: list[dict[str, Any]],
    ridge: float,
    *,
    max_iterations: int = 300,
    tolerance: float = 1e-7,
    aggregate: bool = True,
) -> dict[str, Any]:
    for row in rows:
        if row.get("x") is not None and not math.isfinite(float(row["x"])):
            raise ValueError("response optimizer requires finite x")
        if int(row["outcome"]) not in {0, 1}:
            raise ValueError("response optimizer outcome must be binary")
    for row in rows:
        if row.get("x") is not None and not math.isfinite(float(row["x"])):
            raise ValueError("response optimizer requires finite x")
        if int(row["outcome"]) not in {0, 1}:
            raise ValueError("response optimizer outcome must be binary")
    """Deterministic diagonal-Newton ridge logistic fit on aggregated rows."""

    # Canonical sufficient statistics define the objective identically for both
    # optimized and reference modes; `aggregate` controls reported execution
    # accounting, not floating-point summation order.
    grouped: dict[tuple[Any, ...], list[int]] = defaultdict(lambda: [0, 0])
    for row in rows:
        key = (str(row["channel"]), row.get("x"), str(row["player_model"]), str(row["config_signature"]))
        grouped[key][0] += 1
        grouped[key][1] += int(row["outcome"])
    work_rows = [
        {"channel": key[0], "x": key[1], "player_model": key[2], "config_signature": key[3],
         "count": counts[0], "positive": counts[1]}
        for key, counts in sorted(grouped.items(), key=lambda item: tuple(str(value) for value in item[0]))
    ]
    channels = sorted({str(row["channel"]) for row in work_rows})
    x_values = {
        channel: [(float(row["x"]), int(row["count"])) for row in work_rows if row["channel"] == channel and row.get("x") is not None]
        for channel in channels
    }
    x_scale = {}
    for channel, values in x_values.items():
        total = sum(count for _, count in values)
        x_mean = sum(value * count for value, count in values) / total if total else 0.0
        variance = sum(count * (value - x_mean) ** 2 for value, count in values) / total if total else 0.0
        x_scale[channel] = {
            "mean": x_mean,
            "sd": max(1e-9, sqrt(variance)) if total > 1 else 1.0,
            "min": min((value for value, _ in values), default=None),
            "max": max((value for value, _ in values), default=None),
        }
    coefficients: dict[str, float] = {}
    for channel in channels:
        channel_rows = [row for row in work_rows if row["channel"] == channel]
        channel_count = sum(int(row["count"]) for row in channel_rows)
        rate = (sum(int(row["positive"]) for row in channel_rows) + 0.5) / (channel_count + 1.0)
        coefficients[f"intercept|{channel}"] = math.log(rate / (1.0 - rate))
        if x_values[channel]:
            coefficients[f"slope|{channel}"] = 0.1
    for row in work_rows:
        channel = str(row["channel"])
        coefficients.setdefault(f"model|{channel}|{row['player_model']}", 0.0)
        coefficients.setdefault(f"config|{channel}|{row['config_signature']}", 0.0)

    def objective(candidate: dict[str, float]) -> float:
        total = 0.0
        for row in work_rows:
            channel = str(row["channel"])
            linear = candidate[f"intercept|{channel}"]
            linear += candidate[f"model|{channel}|{row['player_model']}"]
            linear += candidate[f"config|{channel}|{row['config_signature']}"]
            if row.get("x") is not None:
                scale = x_scale[channel]
                standardized = (float(row["x"]) - scale["mean"]) / scale["sd"]
                linear += candidate[f"slope|{channel}"] * standardized
            # count*log(1+exp(z))-positive*z, evaluated stably.
            softplus = linear + math.log1p(math.exp(-linear)) if linear >= 0 else math.log1p(math.exp(linear))
            total += int(row["count"]) * softplus - int(row["positive"]) * linear
        total += 0.5 * ridge * sum(
            value * value for key, value in candidate.items() if key.startswith(("model|", "config|"))
        )
        return total

    encoded_rows = []
    affected: dict[str, list[tuple[int, float]]] = defaultdict(list)
    linear_predictor = []
    for index, row in enumerate(work_rows):
        channel = str(row["channel"])
        keys = [f"intercept|{channel}", f"model|{channel}|{row['player_model']}", f"config|{channel}|{row['config_signature']}"]
        features = [1.0, 1.0, 1.0]
        if row.get("x") is not None:
            keys.append(f"slope|{channel}")
            features.append((float(row["x"]) - x_scale[channel]["mean"]) / x_scale[channel]["sd"])
        encoded_rows.append((row, keys, features))
        linear_predictor.append(sum(coefficients[key] * feature for key, feature in zip(keys, features)))
        for key, feature in zip(keys, features):
            affected[key].append((index, feature))

    def softplus(value: float) -> float:
        return value + math.log1p(math.exp(-value)) if value >= 0 else math.log1p(math.exp(value))

    def projected_kkt() -> float:
        maximum = 0.0
        for key in sorted(coefficients):
            gradient = ridge * coefficients[key] if key.startswith(("model|", "config|")) else 0.0
            for index, feature in affected[key]:
                row = work_rows[index]
                gradient += (int(row["count"]) * _sigmoid(linear_predictor[index]) - int(row["positive"])) * feature
            if key.startswith("slope|") and coefficients[key] <= 1e-8 + 1e-14 and gradient >= 0:
                gradient = 0.0
            maximum = max(maximum, abs(gradient))
        return maximum

    converged = False
    stop_reason = "iteration_limit"
    objective_history = [objective(coefficients)]
    final_max_change = float("inf")
    final_max_gradient = projected_kkt()
    total_backtracks = 0
    last_damping = 1.0
    for iteration in range(1, max_iterations + 1):
        sweep_max_change = 0.0
        stagnated = False
        for key in sorted(coefficients):
            old = coefficients[key]
            gradient = ridge * old if key.startswith(("model|", "config|")) else 0.0
            curvature = ridge if key.startswith(("model|", "config|")) else 0.0
            for index, feature in affected[key]:
                row = work_rows[index]
                probability = _sigmoid(linear_predictor[index])
                gradient += (int(row["count"]) * probability - int(row["positive"])) * feature
                curvature += int(row["count"]) * probability * (1.0 - probability) * feature * feature
            if key.startswith("slope|") and old <= 1e-8 + 1e-14 and gradient >= 0:
                continue
            step = -gradient / max(curvature, 1e-12)
            if key.startswith("slope|"):
                step = max(1e-8 - old, step)
            if step == 0.0:
                continue
            local_old = 0.5 * ridge * old * old if key.startswith(("model|", "config|")) else 0.0
            for index, _ in affected[key]:
                row = work_rows[index]
                eta = linear_predictor[index]
                local_old += int(row["count"]) * softplus(eta) - int(row["positive"]) * eta
            damping = 1.0
            accepted_step = None
            while damping >= 2 ** -30:
                delta = damping * step
                candidate_value = old + delta
                local_new = 0.5 * ridge * candidate_value * candidate_value if key.startswith(("model|", "config|")) else 0.0
                for index, feature in affected[key]:
                    row = work_rows[index]
                    eta = linear_predictor[index] + delta * feature
                    local_new += int(row["count"]) * softplus(eta) - int(row["positive"]) * eta
                if local_new <= local_old:
                    accepted_step = delta
                    break
                damping *= 0.5
                total_backtracks += 1
            last_damping = damping
            if accepted_step is None:
                stagnated = True
                break
            coefficients[key] = old + accepted_step
            for index, feature in affected[key]:
                linear_predictor[index] += accepted_step * feature
            sweep_max_change = max(sweep_max_change, abs(accepted_step))
        final_max_change = sweep_max_change
        objective_history.append(objective(coefficients))
        final_max_gradient = projected_kkt()
        if stagnated:
            stop_reason = "line_search_stagnation"
            break
        if final_max_gradient <= tolerance:
            converged = True
            stop_reason = "projected_kkt"
            break
    return {
        "coefficients": coefficients,
        "x_scale": x_scale,
        "converged": converged,
        "iterations": iteration,
        "max_iterations": max_iterations,
        "tolerance": tolerance,
        "ridge": ridge,
        "optimizer": "sparse_coordinate_newton_with_deterministic_backtracking",
        "final_objective": objective_history[-1],
        "objective_history": objective_history,
        "final_max_change": final_max_change,
        "final_max_gradient": final_max_gradient,
        "projected_kkt_tolerance": tolerance,
        "projected_kkt_pass": final_max_gradient <= tolerance,
        "stop_reason": stop_reason,
        "last_damping": last_damping,
        "total_backtracks": total_backtracks,
        "aggregated_rows": len(work_rows) if aggregate else len(rows),
        "numerical_sufficient_statistic_rows": len(work_rows),
        "aggregation_enabled": aggregate,
        "raw_rows": len(rows),
    }


# Retain the coordinate implementation above as an auditable reference; the
# frozen Model-B optimizer is the zero-sum Newton-PCG implementation below.
_fit_response_coefficients_coordinate_reference = _fit_response_coefficients


def _pcg_solve(hvp, rhs: list[float], precondition, *, target: float, cap: int, active_index: int|None=None) -> tuple[list[float], dict[str, Any]]:
    """Deterministic PCG used by production and dense-reference tests."""
    n=len(rhs); x=[0.0]*n; r=rhs[:]
    if active_index is not None: r[active_index]=0.0
    z=precondition(r); p=z[:]; rz=math.fsum(r[i]*z[i] for i in range(n))
    residual=sqrt(math.fsum(v*v for v in r))
    for iteration in range(1,cap+1):
        if active_index is not None: p[active_index]=0.0
        hp=hvp(p)
        curvature=math.fsum(p[i]*hp[i] for i in range(n))
        if not math.isfinite(curvature) or curvature<=0:
            return x,{"solved":False,"stop_reason":"nonfinite_or_negative_curvature","iterations":iteration,"residual":residual}
        alpha=rz/curvature
        x=[x[i]+alpha*p[i] for i in range(n)]; r=[r[i]-alpha*hp[i] for i in range(n)]
        if active_index is not None: r[active_index]=0.0
        new_rr=math.fsum(v*v for v in r)
        residual=sqrt(new_rr)
        if not math.isfinite(new_rr): return x,{"solved":False,"stop_reason":"nonfinite_residual","iterations":iteration,"residual":residual}
        if residual<=target: return x,{"solved":True,"stop_reason":"residual_target","iterations":iteration,"residual":residual}
        z=precondition(r); nrz=math.fsum(r[i]*z[i] for i in range(n)); p=[z[i]+nrz/rz*p[i] for i in range(n)]; rz=nrz
    return x,{"solved":False,"stop_reason":"iteration_limit","iterations":iteration,"residual":residual}


def _pcg_direction_for_test(matrix: list[list[float]], rhs: list[float], *, target: float = 1e-12) -> tuple[list[float], dict[str, Any]]:
    n=len(rhs)
    return _pcg_solve(lambda p:[math.fsum(matrix[i][j]*p[j] for j in range(n)) for i in range(n)],rhs,lambda r:r[:],target=target,cap=min(2000,max(50,4*n)))


def _sparse_hvp(vector, weights, shift, ridge, penalty_groups, active_index=None):
    terms=[[shift*x] for x in vector]
    for weight,features in weights:
        dot=math.fsum(vector[i]*a for i,a in features.items())
        for i,a in features.items(): terms[i].append(weight*a*dot)
    for inds in penalty_groups:
        total=math.fsum(vector[i] for i in inds)
        for i in inds: terms[i].append(ridge*(vector[i]+total))
    out=[math.fsum(x) for x in terms]
    if active_index is not None: out[active_index]=vector[active_index]
    return out


def _sparse_logistic_numerics_for_test(
    encoded: list[tuple[int,int,dict[int,float]]], beta: list[float], vector: list[float]
) -> tuple[float,list[float],list[float]]:
    """Unpenalized objective/gradient/HVP primitive for numerical contract tests."""
    objective=0.0; gradient=[0.0]*len(beta); hvp=[0.0]*len(beta)
    for n,y,features in encoded:
        eta=math.fsum(beta[i]*v for i,v in features.items()); p=_sigmoid(eta)
        objective+=n*(eta+math.log1p(math.exp(-eta)) if eta>=0 else math.log1p(math.exp(eta)))-y*eta
        error=n*p-y; weight=n*p*(1-p); vd=math.fsum(vector[i]*v for i,v in features.items())
        for i,v in features.items(): gradient[i]+=error*v; hvp[i]+=weight*v*vd
    return objective,gradient,hvp


def _projected_armijo(objective, beta, direction, gradient, project=lambda x:x):
    """Exact projected Armijo loop used to exercise stagnation/finite guards."""
    old=objective(beta); alpha=1.0
    while alpha>=2**-30:
        candidate=project([beta[i]+alpha*direction[i] for i in range(len(beta))])
        step_dot=math.fsum(gradient[i]*(candidate[i]-beta[i]) for i in range(len(beta)))
        value=objective(candidate)
        if step_dot < 0.0 and math.isfinite(value) and value <= old + 1e-4 * step_dot:
            return candidate, value, alpha
        alpha*=.5
    return None,None,alpha


_armijo_projected_for_test = _projected_armijo


def _fit_response_coefficients(
    rows: list[dict[str, Any]], ridge: float, *, max_iterations: int = 300,
    tolerance: float = 1e-7, aggregate: bool = True,
) -> dict[str, Any]:
    for row in rows:
        if row.get("x") is not None and not math.isfinite(float(row["x"])):
            raise ValueError("response optimizer requires finite x")
        if int(row["outcome"]) not in {0, 1}:
            raise ValueError("response optimizer outcome must be binary")
    grouped: dict[tuple[Any, ...], list[int]] = defaultdict(lambda: [0, 0])
    for row in rows:
        key = (str(row["channel"]), row.get("x"), str(row["player_model"]), str(row["config_signature"]))
        grouped[key][0] += 1; grouped[key][1] += int(row["outcome"])
    work = [{"channel": k[0], "x": k[1], "model": k[2], "config": k[3], "n": v[0], "y": v[1]}
            for k, v in sorted(grouped.items(), key=lambda item: tuple(str(x) for x in item[0]))]
    all_coefficients: dict[str, float] = {}
    x_scale: dict[str, Any] = {}
    audits = []; histories = []; channel_passes=[]; channel_kkts=[]; channel_stops=[]
    for channel in sorted({r["channel"] for r in work}):
        cr = [r for r in work if r["channel"] == channel]
        models = sorted({r["model"] for r in cr}); configs = sorted({r["config"] for r in cr})
        xv = [(float(r["x"]), r["n"]) for r in cr if r["x"] is not None]
        nt = sum(n for _, n in xv); xm = math.fsum(x*n for x, n in xv)/nt if nt else 0.0
        xs = max(1e-9, sqrt(math.fsum(n*(x-xm)**2 for x, n in xv)/nt)) if nt > 1 else 1.0
        x_scale[channel] = {"mean": xm, "sd": xs, "min": min((x for x,_ in xv), default=None), "max": max((x for x,_ in xv), default=None)}
        mi={m:i for i,m in enumerate(models[:-1])}; ci={c:i+len(mi) for i,c in enumerate(configs[:-1])}
        intercept_i=len(mi)+len(ci); slope_i=intercept_i+1 if xv else None; dim=intercept_i+1+(1 if xv else 0)
        enc=[]
        for r in cr:
            f={intercept_i:1.0}
            if len(models)>1:
                if r["model"]==models[-1]:
                    for i in mi.values(): f[i]=-1.0
                else: f[mi[r["model"]]]=1.0
            if len(configs)>1:
                if r["config"]==configs[-1]:
                    for i in ci.values(): f[i]=-1.0
                else: f[ci[r["config"]]]=1.0
            if slope_i is not None: f[slope_i]=(float(r["x"])-xm)/xs
            enc.append((r,f))
        beta=[0.0]*dim; rate=(sum(r["y"] for r in cr)+.5)/(sum(r["n"] for r in cr)+1)
        beta[intercept_i]=math.log(rate/(1-rate));
        if slope_i is not None: beta[slope_i]=.1
        def penalty(b):
            ms=math.fsum(b[i] for i in mi.values()); cs=math.fsum(b[i] for i in ci.values())
            return .5*ridge*math.fsum([*(b[i]**2 for i in mi.values()),ms*ms,*(b[i]**2 for i in ci.values()),cs*cs])
        def obj(b):
            terms=[penalty(b)]
            for r,f in enc:
                eta=math.fsum(b[i]*v for i,v in f.items()); sp=eta+math.log1p(math.exp(-eta)) if eta>=0 else math.log1p(math.exp(eta))
                terms.append(r["n"]*sp-r["y"]*eta)
            return math.fsum(terms)
        def gh(b):
            gterms=[[] for _ in range(dim)]; dterms=[[] for _ in range(dim)]; weights=[]
            for r,f in enc:
                eta=math.fsum(b[i]*v for i,v in f.items()); p=_sigmoid(eta); e=r["n"]*p-r["y"]; w=r["n"]*p*(1-p); weights.append((w,f))
                for i,v in f.items(): gterms[i].append(e*v); dterms[i].append(w*v*v)
            for inds in (list(mi.values()),list(ci.values())):
                s=math.fsum(b[i] for i in inds)
                for i in inds: gterms[i].append(ridge*(b[i]+s)); dterms[i].append(2*ridge)
            return [math.fsum(x) for x in gterms],[math.fsum(x) for x in dterms],weights
        def hv(v,weights,shift):
            return _sparse_hvp(v,weights,shift,ridge,(list(mi.values()),list(ci.values())))
        def original_kkt(b):
            """Raw constrained KKT in reconstructed original coordinates."""
            scores_m={m:[] for m in models}; scores_c={c:[] for c in configs}
            giterms=[]; gsterms=[]
            for r,f in enc:
                eta=math.fsum(b[i]*v for i,v in f.items()); error=r["n"]*_sigmoid(eta)-r["y"]
                giterms.append(error); scores_m[r["model"]].append(error); scores_c[r["config"]].append(error)
                if slope_i is not None: gsterms.append(error*f[slope_i])
            gi=math.fsum(giterms); gs=math.fsum(gsterms)
            mvals={m:(b[mi[m]] if m in mi else -math.fsum(b[i] for i in mi.values())) for m in models}
            cvals={c:(b[ci[c]] if c in ci else -math.fsum(b[i] for i in ci.values())) for c in configs}
            mg=[math.fsum(scores_m[m])+ridge*mvals[m] for m in models]; cg=[math.fsum(scores_c[c])+ridge*cvals[c] for c in configs]
            keyed={"intercept":gi,**{f"model:{m}":v for m,v in zip(models,mg)},**{f"config:{c}":v for c,v in zip(configs,cg)}}
            if slope_i is not None: keyed["slope"]=0.0 if b[slope_i]<=1e-8+1e-14 and gs>=0 else gs
            worst=max(keyed,key=lambda k:abs(keyed[k])); return abs(keyed[worst]),worst,keyed
        hist=[obj(beta)]; pcg_records=[]; armijo_records=[]; active_history=[]; raw_kkt_history=[]; converged=False; stop="iteration_limit"; backtracks=0; last_damping=1.0; channel_max_change=0.0
        for iteration in range(1,max_iterations+1):
            g,diag,w=gh(beta)
            active_slope=slope_i is not None and beta[slope_i]<=1e-8+1e-14 and g[slope_i]>=0
            if active_slope: g[slope_i]=0.0
            kkt,worst_key,_=original_kkt(beta); raw_kkt_history.append(kkt); active_history.append(active_slope)
            if kkt<=tolerance: converged=True; stop="projected_kkt"; break
            solved=False
            residual_target=max(1e-12,min(.5,sqrt(kkt))*kkt)
            pcg_cap=min(2000,max(50,4*dim))
            shift_attempts=[]
            for shift in (0.0,1e-12,1e-10,1e-8,1e-6,1e-4):
                rhs=[-x for x in g]; d=[0.0]*dim; r=rhs[:]
                # Exact unpenalized intercept/slope block; all contrast
                # coordinates use their declared diagonal curvature.
                cross=0.0
                if slope_i is not None:
                    for weight,features in w:
                        cross+=weight*features.get(intercept_i,0.0)*features.get(slope_i,0.0)
                def precondition(vector):
                    out=[vector[i]/max(diag[i]+shift,1e-12) for i in range(dim)]
                    if slope_i is None or active_slope:
                        out[intercept_i]=vector[intercept_i]/max(diag[intercept_i]+shift,1e-12)
                        if active_slope: out[slope_i]=0.0
                    else:
                        a=diag[intercept_i]+shift; c=diag[slope_i]+shift; determinant=max(a*c-cross*cross,1e-18)
                        out[intercept_i]=(c*vector[intercept_i]-cross*vector[slope_i])/determinant
                        out[slope_i]=(a*vector[slope_i]-cross*vector[intercept_i])/determinant
                    return out
                d,pcg_audit=_pcg_solve(
                    lambda p:_sparse_hvp(p,w,shift,ridge,(list(mi.values()),list(ci.values())),slope_i if active_slope else None),
                    rhs,precondition,target=residual_target,cap=pcg_cap,
                    active_index=slope_i if active_slope else None,
                )
                pcgit=pcg_audit["iterations"]; residual_norm=pcg_audit["residual"]
                solved=pcg_audit["solved"]; failure=None if solved else pcg_audit["stop_reason"]
                candidate_curvature=None; candidate_descent=None
                if solved:
                    candidate_hd=hv(d,w,shift)
                    candidate_curvature=math.fsum(d[i]*candidate_hd[i] for i in range(dim))
                    candidate_descent=math.fsum(g[i]*d[i] for i in range(dim))
                    if (not math.isfinite(candidate_curvature) or candidate_curvature<=0 or
                            not math.isfinite(candidate_descent) or candidate_descent>=0):
                        failure="nonfinite_nondescent_or_nonpositive_curvature"; solved=False
                shift_attempts.append({"shift":shift,"iterations":pcgit,"residual":residual_norm,"target":residual_target,"curvature_failure":failure,"curvature_product":candidate_curvature,"descent_product":candidate_descent,"solved":solved})
                if solved: break
            hd=hv(d,w,shift) if solved else None
            curvature_product=math.fsum(d[i]*hd[i] for i in range(dim)) if solved else None
            directional=math.fsum(g[i]*d[i] for i in range(dim)) if solved else None
            pcg_records.append({"iteration":iteration,"current_projected_kkt":kkt,"shift":shift,"shift_attempts":shift_attempts,"pcg_iterations":pcgit,"solved":solved,"absolute_residual_target":residual_target,"final_residual":residual_norm,"iteration_cap":pcg_cap,"curvature_product":curvature_product,"descent_product":directional})
            if not solved: stop="pcg_nonconvergence"; break
            if not math.isfinite(directional) or directional>=0 or not math.isfinite(curvature_product) or curvature_product<=0: stop="pcg_nondescent_or_nonpositive_curvature"; break
            project=(lambda candidate: [max(1e-8,x) if i==slope_i else x for i,x in enumerate(candidate)]) if slope_i is not None else (lambda candidate:candidate)
            cand,no,damping=_projected_armijo(obj,beta,d,g,project)
            accepted=(cand,no) if cand is not None else None
            iteration_backtracks=(int(round(-math.log2(damping))) if accepted is not None else 31)
            backtracks+=iteration_backtracks
            last_damping=damping
            armijo_records.append({"iteration":iteration,"alpha":damping,"backtracks":iteration_backtracks,"passed":accepted is not None})
            if accepted is None: stop="line_search_stagnation"; break
            previous=beta; beta,no=accepted; channel_max_change=max(channel_max_change,max(abs(beta[i]-previous[i]) for i in range(dim))); hist.append(no)
        g,_,_=gh(beta)
        if slope_i is not None and beta[slope_i]<=1e-8+1e-14 and g[slope_i]>=0:g[slope_i]=0.0
        kkt,worst_key,_=original_kkt(beta); raw_kkt_history.append(kkt)
        if kkt<=tolerance: converged=True; stop="projected_kkt"
        model_vals={m:(beta[mi[m]] if m in mi else -sum(beta[i] for i in mi.values())) for m in models}
        config_vals={c:(beta[ci[c]] if c in ci else -sum(beta[i] for i in ci.values())) for c in configs}
        all_coefficients[f"intercept|{channel}"]=beta[intercept_i]
        if slope_i is not None: all_coefficients[f"slope|{channel}"]=beta[slope_i]
        all_coefficients.update({f"model|{channel}|{m}":v for m,v in model_vals.items()}); all_coefficients.update({f"config|{channel}|{c}":v for c,v in config_vals.items()})
        order="|".join([channel,*models,*configs,"intercept",*( ["slope"] if slope_i is not None else [])])
        _,_,raw_keyed=original_kkt(beta)
        audits.append({"channel":channel,"dimension":dim,"models":len(models),"configs":len(configs),"zero_sum_model":math.fsum(model_vals.values()),"zero_sum_config":math.fsum(config_vals.values()),"coefficient_order_sha256":hashlib.sha256(order.encode()).hexdigest(),"free_vector_coefficient_order":order,"active_slope":bool(slope_i is not None and beta[slope_i]<=1e-8+1e-14),"active_slope_history":active_history,"objective_history":hist,"raw_kkt_history":raw_kkt_history,"raw_kkt_final":kkt,"raw_kkt_worst_key":worst_key,"raw_kkt_worst_value":raw_keyed[worst_key],"stop_reason":stop,"projected_kkt":kkt,"iterations":iteration,"max_change":channel_max_change,"last_damping":last_damping,"total_backtracks":backtracks,"preconditioner":{"block":"intercept_slope_2x2" if slope_i is not None else "intercept_1x1","contrast_diagonal":True,"pivot_floor":1e-18},"pcg":pcg_records,"armijo":armijo_records})
        histories.append(hist); channel_passes.append(converged and kkt<=tolerance); channel_kkts.append(kkt); channel_stops.append(stop)
    final_obj=math.fsum(h[-1] for h in histories); overall=bool(histories) and all(channel_passes)
    overall_stop="projected_kkt" if overall else next((s for s in channel_stops if s!="projected_kkt"),"iteration_limit")
    max_len=max(map(len,histories),default=0); aggregate_history=[math.fsum(h[min(i,len(h)-1)] for h in histories) for i in range(max_len)]
    return {"coefficients":all_coefficients,"x_scale":x_scale,"converged":overall,"iterations":max((len(h)-1 for h in histories),default=0),"max_iterations":max_iterations,"tolerance":tolerance,"ridge":ridge,"optimizer":"zero_sum_sparse_newton_pcg_with_armijo","final_objective":final_obj,"objective_history":aggregate_history,"final_max_change":max((a["max_change"] for a in audits),default=0.0),"final_max_gradient":max(channel_kkts,default=float('inf')),"projected_kkt_tolerance":tolerance,"projected_kkt_pass":overall,"stop_reason":overall_stop,"last_damping":min((a["last_damping"] for a in audits),default=1.0),"total_backtracks":sum(a["total_backtracks"] for a in audits),"pcg_residual_rule":"max(1e-12,min(.5,sqrt(current_projected_kkt))*current_projected_kkt)","pcg_iteration_cap_rule":"min(2000,max(50,4*free_parameter_count))","pcg_shift_schedule":[0.0,1e-12,1e-10,1e-8,1e-6,1e-4],"pcg_preconditioner":"exact_intercept_slope_block_plus_diagonal_contrasts","armijo_c1":1e-4,"contrast_audit":audits,"aggregated_rows":len(work) if aggregate else len(rows),"numerical_sufficient_statistic_rows":len(work),"aggregation_enabled":aggregate,"raw_rows":len(rows)}


def _response_probability(fit: dict[str, Any], row: dict[str, Any]) -> float:
    channel = str(row["channel"])
    coefficients = fit["coefficients"]
    linear = coefficients.get(f"intercept|{channel}", 0.0)
    linear += coefficients.get(f"model|{channel}|{row['player_model']}", 0.0)
    linear += coefficients.get(f"config|{channel}|{row['config_signature']}", 0.0)
    if row.get("x") is not None:
        scale = fit["x_scale"][channel]
        standardized = (float(row["x"]) - scale["mean"]) / scale["sd"]
        linear += coefficients.get(f"slope|{channel}", 0.0) * standardized
    return _sigmoid(linear)


def response_probability(
    fit: dict[str, Any],
    *,
    channel: str,
    player_model: str,
    signature: str,
    x: float | None,
) -> float:
    """Public decision-level probability for OOF log-loss/Brier scoring."""

    if fit.get("status") != "ok" or channel not in fit.get("x_scale", {}):
        raise ValueError(f"response channel unavailable: {channel}")
    return _response_probability(fit, {
        "channel": channel,
        "player_model": player_model,
        "config_signature": signature,
        "x": x,
    })


def fit_hierarchical_responses(
    rows: Iterable[dict[str, Any]],
    *,
    ridge_grid: tuple[float, ...] = _RIDGE_GRID,
) -> dict[str, Any]:
    """Fit response channels with training-only game-hash ridge selection."""

    materialized = [dict(row) for row in rows]
    if not materialized:
        return {"status": "unavailable", "reason": "no_training_rows", "ridge_grid": list(ridge_grid)}
    cv: dict[str, float] = {}
    inner_cv_convergence: dict[str, list[dict[str, Any]]] = {}
    for ridge in ridge_grid:
        losses = []
        fold_records = []
        for fold in range(3):
            training = [row for row in materialized if _game_fold(str(row["game_id"])) != fold]
            validation = [row for row in materialized if _game_fold(str(row["game_id"])) == fold]
            record = {
                "fold": fold,
                "training_rows": len(training),
                "validation_rows": len(validation),
                "training_games": len({str(row["game_id"]) for row in training}),
                "validation_games": len({str(row["game_id"]) for row in validation}),
            }
            if not training or not validation:
                record.update({
                    "converged": False, "stop_reason": "missing_training_or_validation_partition",
                    "projected_kkt_norm": float("inf"), "projected_kkt_tolerance": 1e-7,
                    "projected_kkt_pass": False, "iterations": 0,
                    "finite_validation_probability": False, "finite_validation_loss": False,
                    "fold_logloss": float("inf"),
                    "solver_audit": None,
                })
                fold_records.append(record)
                continue
            fitted = _fit_response_coefficients(training, ridge)
            record.update({
                "converged": bool(fitted["converged"]),
                "stop_reason": fitted["stop_reason"],
                "projected_kkt_norm": fitted["final_max_gradient"],
                "projected_kkt_tolerance": fitted["projected_kkt_tolerance"],
                "projected_kkt_pass": bool(fitted["projected_kkt_pass"]),
                "iterations": fitted["iterations"],
                "solver_audit": {
                    key: fitted.get(key) for key in (
                        "optimizer", "pcg_residual_rule", "pcg_iteration_cap_rule", "pcg_shift_schedule", "pcg_preconditioner", "armijo_c1",
                        "last_damping", "total_backtracks", "contrast_audit",
                    )
                },
            })
            if not fitted["converged"] or not fitted["projected_kkt_pass"]:
                record.update({
                    "finite_validation_probability": False, "finite_validation_loss": False,
                    "fold_logloss": float("inf"),
                })
                fold_records.append(record)
                continue
            fold_losses = []
            finite_probability = True
            for row in validation:
                raw_probability = _response_probability(fitted, row)
                finite_probability = finite_probability and math.isfinite(raw_probability)
                probability = min(1 - 1e-12, max(1e-12, raw_probability))
                outcome = int(row["outcome"])
                fold_losses.append(-(outcome * math.log(probability) + (1 - outcome) * math.log(1 - probability)))
            finite_loss = bool(fold_losses) and all(math.isfinite(value) for value in fold_losses)
            fold_logloss = mean(fold_losses) if finite_probability and finite_loss else float("inf")
            record.update({
                "finite_validation_probability": finite_probability,
                "finite_validation_loss": finite_loss,
                "fold_logloss": fold_logloss,
            })
            fold_records.append(record)
            if math.isfinite(fold_logloss):
                losses.extend(fold_losses)
        inner_cv_convergence[str(ridge)] = fold_records
        eligible_record = len(fold_records) == 3 and all(
            record["converged"] and record["projected_kkt_pass"]
            and record["finite_validation_probability"] and record["finite_validation_loss"]
            and math.isfinite(record["fold_logloss"])
            for record in fold_records
        )
        cv[str(ridge)] = mean(losses) if losses and eligible_record else float("inf")
    eligible = [ridge for ridge in ridge_grid if math.isfinite(cv[str(ridge)])]
    if not eligible:
        return {
            "status": "unavailable", "reason": "no_ridge_with_all_inner_folds_converged",
            "ridge_grid": list(ridge_grid), "cv_log_loss": cv,
            "inner_cv_convergence": inner_cv_convergence,
            "eligible_ridges": [],
            "ridge_tie_rule": "minimum pooled validation-decision logloss; exact ties choose larger ridge",
        }
    selected = min(eligible, key=lambda ridge: (cv[str(ridge)], -ridge))
    fitted = _fit_response_coefficients(materialized, selected)
    channel_support = {}
    for channel in sorted({str(row["channel"]) for row in materialized}):
        channel_rows = [row for row in materialized if row["channel"] == channel]
        channel_support[channel] = {
            "rows": len(channel_rows),
            "positive": sum(int(row["outcome"]) for row in channel_rows),
            "games": len({str(row["game_id"]) for row in channel_rows}),
            "models": len({str(row["player_model"]) for row in channel_rows}),
            "config_signatures": len({str(row["config_signature"]) for row in channel_rows}),
        }
    fitted.update({
        "status": "ok" if fitted["converged"] else "unavailable",
        "reason": None if fitted["converged"] else "selected_ridge_final_fit_nonconverged",
        "ridge_grid": list(ridge_grid),
        "cv_log_loss": cv,
        "inner_cv_convergence": inner_cv_convergence,
        "eligible_ridges": list(eligible),
        "ridge_tie_rule": "minimum pooled validation-decision logloss; exact ties choose larger ridge",
        "selected_ridge": selected,
        "selection": "three_fold_sha256_game_id; minimum pooled validation-decision logloss; exact ties choose larger ridge",
        "training_rows": len(materialized),
        "training_games": len({str(row["game_id"]) for row in materialized}),
        "training_models": len({str(row["player_model"]) for row in materialized}),
        "training_config_signatures": len({str(row["config_signature"]) for row in materialized}),
        "channel_support": channel_support,
    })
    return fitted


def response_parameter(
    fit: dict[str, Any],
    *,
    channel: str,
    player_model: str,
    signature: str,
) -> tuple[float | None, dict[str, Any]]:
    """Return a fitted probability or monotone p=.5 threshold with provenance."""

    provenance = {
        key: fit.get(key)
        for key in ("status", "selected_ridge", "eligible_ridges", "ridge_tie_rule", "converged", "iterations", "training_rows", "training_games", "training_models", "training_config_signatures", "optimizer", "final_objective", "final_max_change", "final_max_gradient", "projected_kkt_tolerance", "projected_kkt_pass", "stop_reason", "last_damping", "total_backtracks", "pcg_residual_rule", "pcg_iteration_cap_rule", "pcg_shift_schedule", "pcg_preconditioner", "armijo_c1", "contrast_audit", "inner_cv_convergence")
    }
    provenance["channel_support"] = (fit.get("channel_support") or {}).get(channel)
    if fit.get("status") != "ok" or channel not in fit.get("x_scale", {}):
        return None, provenance
    scale = fit["x_scale"][channel]
    row = {"channel": channel, "player_model": player_model, "config_signature": signature, "x": None}
    if scale.get("min") is None:
        probability = _response_probability(fit, row)
        provenance["parameter_kind"] = "probability"
        return probability, provenance
    coefficients = fit["coefficients"]
    intercept = coefficients.get(f"intercept|{channel}", 0.0)
    intercept += coefficients.get(f"model|{channel}|{player_model}", 0.0)
    intercept += coefficients.get(f"config|{channel}|{signature}", 0.0)
    slope = max(1e-8, coefficients.get(f"slope|{channel}", 1e-8))
    raw = scale["mean"] - intercept * scale["sd"] / slope
    clipped = min(float(scale["max"]), max(float(scale["min"]), raw))
    provenance.update({"parameter_kind": "p50_threshold", "raw_threshold": raw, "fit_min": scale["min"], "fit_max": scale["max"], "clipped": clipped != raw, "monotone_slope": slope})
    return clipped, provenance


def config_signature(family: str, config: dict[str, Any], *, coarse: bool = False) -> str:
    """Deterministic configuration key used by fit and production draws."""

    if not coarse:
        return canonical_config_key(family, config)
    config = canonical_config(family, config)
    def number(name: str, default: float = 0.0) -> float:
        value = config.get(name)
        return default if value is None else float(value)
    if family == "bargaining":
        selected = {
            "max_rounds": config.get("max_rounds"),
            "complete_information": config.get("complete_information"),
            "messages_allowed": config.get("messages_allowed"),
            "delta_1": round(number("delta_1", 1.0) / 0.05) * 0.05,
            "delta_2": round(number("delta_2", 1.0) / 0.05) * 0.05,
        }
    elif family == "negotiation":
        selected = {
            "max_rounds": config.get("max_rounds"),
            "complete_information": config.get("complete_information"),
            "messages_allowed": config.get("messages_allowed"),
            "seller_value": round(number("seller_value"), 1),
            "buyer_value": round(number("buyer_value"), 1),
        }
    else:
        selected = {
            "p": round(number("p"), 1),
            "v": round(number("v"), 1),
            "c": round(number("c"), 1),
            "is_seller_know_cv": config.get("is_seller_know_cv"),
            "is_buyer_know_p": config.get("is_buyer_know_p"),
            "seller_message_type": config.get("seller_message_type"),
            "is_myopic": config.get("is_myopic"),
        }
    return json.dumps(selected, sort_keys=True, separators=(",", ":"), default=str)


def _actor_model(event: dict[str, Any], role: str) -> str:
    """Stable actor identity available in the released corpus."""

    first_roles = {"player_1", "seller"}
    field = "player_1_model" if role in first_roles else "player_2_model"
    return str(event.get(field) or "unknown")


def _keeps_outer_event(
    event: dict[str, Any],
    *,
    outer_keep: Callable[[dict[str, Any]], bool] | None,
    crossfit_manifest: Any,
    excluded_fold: int | None,
    crossfit_axis: str | None,
) -> bool:
    if outer_keep is not None and not outer_keep(event):
        return False
    if crossfit_manifest is not None and excluded_fold is not None:
        return row_fold(event, str(crossfit_axis), crossfit_manifest) != excluded_fold
    return True


def extract_response_observations(
    events: Iterable[dict[str, Any]],
    *,
    outer_keep: Callable[[dict[str, Any]], bool] | None = None,
    crossfit_manifest: Any = None,
    excluded_fold: int | None = None,
    crossfit_axis: str | None = None,
) -> list[dict[str, Any]]:
    """Project legal decisions into production response-model units.

    `outer_keep` is the preferred fold hook. The manifest arguments are accepted
    for the shared crossfit router and require it to expose `fold_for_event`;
    the excluded fold is routed through `crossfit.row_fold` and never inspected
    by any fitting statistic.
    """

    rows = []
    for event in events:
        if not _keeps_outer_event(event, outer_keep=outer_keep, crossfit_manifest=crossfit_manifest,
                                  excluded_fold=excluded_fold, crossfit_axis=crossfit_axis):
            continue
        family = str(event.get("game_family") or "")
        role = str(event.get("role") or "")
        action_type = str(event.get("action_type") or "")
        config = as_dict(event.get("configuration") or event.get("public_parameters"))
        raw = as_dict(event.get("raw_record"))
        outcome: int | None = None
        x: float | None = None
        channel: str | None = None
        if family == "bargaining" and action_type == "decision":
            offer = last_transcript_action(event, "offer") or {}
            money = as_float(config.get("money_to_divide")) or 100.0
            x = bargaining_share_to_responder(offer, role, money)
            decision = str(raw.get("decision") or event.get("accept_reject") or "").lower()
            if x is not None and decision:
                outcome = int(decision == "accept")
                channel = f"bargaining|{role}"
        elif family == "negotiation" and action_type == "decision":
            offer = last_transcript_action(event, "offer") or {}
            order = as_float(config.get("product_price_order")) or 1_000_000.0
            price = as_float(offer.get("numeric_action"))
            if price is None:
                price = as_float(as_dict(offer.get("raw")).get("product_price"))
            own = as_float(config.get("seller_value" if role == "seller" else "buyer_value"))
            decision = str(raw.get("decision") or event.get("accept_reject") or "")
            if price is not None and own is not None and decision:
                normalized = price / order
                x = normalized - own if role == "seller" else own - normalized
                outcome = int(decision == "AcceptOffer")
                channel = f"negotiation|{role}"
        elif family == "persuasion" and role == "seller" and action_type in {"recommendation", "message"}:
            quality = persuasion_round_quality(event)
            decision = persuasion_recommendation(event) or raw.get("decision")
            if quality in {"high-quality", "low-quality"} and decision in {"yes", "no"}:
                channel = "persuasion|seller_high" if quality == "high-quality" else "persuasion|seller_low"
                outcome = int(decision == "yes")
        elif family == "persuasion" and role == "buyer" and action_type == "buy_decision":
            recommendation = persuasion_recommendation(same_round_transcript_item(event, role="seller"))
            decision = raw.get("decision") or event.get("buy_no_buy")
            if recommendation in {"yes", "no"} and decision in {"yes", "no"}:
                channel = "persuasion|buyer_yes" if recommendation == "yes" else "persuasion|buyer_no"
                outcome = int(decision == "yes")
        if channel is not None and outcome is not None:
            event_identity = event.get("event_id")
            if not event_identity:
                identity_payload = {
                    "game_id": event.get("game_id"), "round": event.get("round"), "role": role,
                    "action_type": action_type, "raw_record": raw,
                }
                event_identity = hashlib.sha256(
                    json.dumps(identity_payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
                ).hexdigest()[:24]
            rows.append({
                "decision_id": str(event_identity),
                "family": family,
                "game_family": family,
                "role": role,
                "channel": channel,
                "outcome": outcome,
                "x": x,
                "game_id": str(event.get("game_id") or "unknown"),
                "player_model": _actor_model(event, role),
                "player_1_model": event.get("player_1_model"),
                "player_2_model": event.get("player_2_model"),
                "configuration": canonical_config(family, config),
                "config_signature": config_signature(family, config),
            })
    return rows


def extract_joint_bundle_observations(events: Any) -> list[dict[str, Any]]:
    """Extract raw identifiable Model-B endpoints by model/config/role.

    This helper deliberately performs no normalization, latent scoring, shrinkage,
    or missing-value imputation, so holdout diagnostics can evaluate the exact same
    endpoints without learning from the holdout.
    """

    stats: dict[tuple[str, str, str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "offers": [],
            "first_offers": [],
            "offer_sequences": defaultdict(list),
            "concessions": [],
            "accept_margins": [],
            "decision_curve": defaultdict(lambda: [0, 0]),
            "truth": [0, 0],
            "yes_low": [0, 0],
            "buy_yes": [0, 0],
            "buy_no": [0, 0],
            "games": set(),
            "parameter_games": defaultdict(set),
            "configuration": None,
        }
    )
    last_offer: dict[tuple[str, str], float] = {}
    for event in events:
        family = str(event.get("game_family") or "")
        role = str(event.get("role") or "")
        if family not in {"bargaining", "negotiation", "persuasion"} or not role:
            continue
        config_id = str(event.get("config_id") or "unknown")
        model = _actor_model(event, role)
        key = (family, model, config_id, role)
        bucket = stats[key]
        bucket["games"].add(str(event.get("game_id") or "unknown"))
        config = as_dict(event.get("configuration") or event.get("public_parameters"))
        if bucket["configuration"] is None:
            bucket["configuration"] = config
        raw = as_dict(event.get("raw_record"))
        game_role = (str(event.get("game_id")), role)
        game_id = str(event.get("game_id") or "unknown")

        if family == "bargaining":
            share = bargaining_offer_self_share(event)
            if share is not None:
                bucket["offers"].append(share)
                bucket["offer_sequences"][game_id].append(share)
                bucket["parameter_games"]["target_share"].add(game_id)
                previous = last_offer.get(game_role)
                if previous is None:
                    bucket["first_offers"].append(share)
                else:
                    bucket["concessions"].append(previous - share)
                    bucket["parameter_games"]["concession_rate"].add(game_id)
                last_offer[game_role] = share
            elif event.get("action_type") == "decision":
                offer = last_transcript_action(event, "offer")
                money = as_float(config.get("money_to_divide")) or 100.0
                offered = bargaining_share_to_responder(offer or {}, role, money)
                if offered is not None:
                    binned = round(min(1.0, max(0.0, offered)) * 20) / 20
                    accepted = int(str(raw.get("decision") or "").lower() == "accept")
                    bucket["decision_curve"][binned][0] += accepted
                    bucket["decision_curve"][binned][1] += 1
                    bucket["parameter_games"]["accept_threshold"].add(game_id)
        elif family == "negotiation":
            price = negotiation_normalized_price(event)
            if price is not None:
                bucket["offers"].append(price)
                bucket["offer_sequences"][game_id].append(price)
                bucket["parameter_games"]["aspiration_price"].add(game_id)
                previous = last_offer.get(game_role)
                if previous is None:
                    bucket["first_offers"].append(price)
                else:
                    delta = previous - price if role == "seller" else price - previous
                    if -0.5 <= delta <= 0.5:
                        bucket["concessions"].append(delta)
                        bucket["parameter_games"]["concession_rate"].add(game_id)
                last_offer[game_role] = price
            elif event.get("action_type") == "decision":
                offer = last_transcript_action(event, "offer") or {}
                order = as_float(config.get("product_price_order")) or 1_000_000.0
                accepted_price = as_float(offer.get("numeric_action"))
                if accepted_price is None:
                    accepted_price = as_float(as_dict(offer.get("raw")).get("product_price"))
                own = as_float(config.get("seller_value" if role == "seller" else "buyer_value"))
                if accepted_price is not None and own is not None and order > 0:
                    normalized = accepted_price / order
                    margin = normalized - own if role == "seller" else own - normalized
                    binned = round(margin * 20) / 20
                    accepted = int(str(raw.get("decision") or "") == "AcceptOffer")
                    bucket["decision_curve"][binned][0] += accepted
                    bucket["decision_curve"][binned][1] += 1
                    bucket["parameter_games"]["accept_margin"].add(game_id)
        else:
            if role == "seller" and event.get("action_type") in {"recommendation", "message"}:
                quality = persuasion_round_quality(event)
                recommendation = persuasion_recommendation(event) or raw.get("decision")
                if quality and recommendation in {"yes", "no"}:
                    if quality == "high-quality":
                        bucket["truth"][0] += int(recommendation == "yes")
                        bucket["truth"][1] += 1
                        bucket["parameter_games"]["honesty"].add(game_id)
                    if quality == "low-quality":
                        bucket["yes_low"][0] += int(recommendation == "yes")
                        bucket["yes_low"][1] += 1
                        bucket["parameter_games"]["yes_on_low_rate"].add(game_id)
            elif role == "buyer" and event.get("action_type") == "buy_decision":
                recommendation = persuasion_recommendation(same_round_transcript_item(event, role="seller"))
                bought = raw.get("decision") or event.get("buy_no_buy")
                if recommendation in {"yes", "no"} and bought in {"yes", "no"}:
                    target = bucket["buy_yes" if recommendation == "yes" else "buy_no"]
                    target[0] += int(bought == "yes")
                    target[1] += 1
                    parameter = "trust_prior" if recommendation == "yes" else "buy_after_no_rate"
                    bucket["parameter_games"][parameter].add(game_id)

    rows: list[dict[str, Any]] = []
    for (family, model, config_id, role), bucket in sorted(stats.items()):
        params: dict[str, float] = {}
        counts: dict[str, int] = {}
        if family == "bargaining":
            if bucket["first_offers"]:
                params["target_share"] = mean(bucket["first_offers"])
                counts["target_share"] = len(bucket["first_offers"])
            if bucket["concessions"]:
                params["concession_rate"] = mean(bucket["concessions"])
                counts["concession_rate"] = len(bucket["concessions"])
            threshold = _threshold_crossing(bucket["decision_curve"])
            if threshold is not None:
                params["accept_threshold"] = threshold
                counts["accept_threshold"] = sum(v[1] for v in bucket["decision_curve"].values())
        elif family == "negotiation":
            if bucket["first_offers"]:
                params["aspiration_price"] = mean(bucket["first_offers"])
                counts["aspiration_price"] = len(bucket["first_offers"])
            if bucket["concessions"]:
                params["concession_rate"] = mean(bucket["concessions"])
                counts["concession_rate"] = len(bucket["concessions"])
            threshold = _threshold_crossing(bucket["decision_curve"])
            if threshold is not None:
                params["accept_margin"] = threshold
                counts["accept_margin"] = sum(v[1] for v in bucket["decision_curve"].values())
        if family in {"bargaining", "negotiation"} and bucket["first_offers"] and bucket["concessions"]:
            intercept = mean(bucket["first_offers"])
            slope = mean(bucket["concessions"])
            residuals = []
            for sequence in bucket["offer_sequences"].values():
                for index, observed in enumerate(sequence):
                    predicted = intercept - slope * index if family == "bargaining" or role == "seller" else intercept + slope * index
                    residuals.append(observed - predicted)
            if len(residuals) >= 2:
                params["action_noise"] = sqrt(3.0) * pstdev(residuals)
                counts["action_noise"] = len(residuals)
                bucket["parameter_games"]["action_noise"].update(bucket["offer_sequences"].keys())
        if family == "persuasion":
            sources = (("honesty", "truth"), ("yes_on_low_rate", "yes_low")) if role == "seller" else (
                ("trust_prior", "buy_yes"), ("buy_after_no_rate", "buy_no")
            )
            for name, source in sources:
                hits, total = bucket[source]
                if total:
                    params[name] = hits / total
                    counts[name] = total
        rows.append({
            "bundle_id": f"{family}|{model}|{config_id}|{role}",
            "family": family,
            "player_model": model,
            "actor_model_is_holdout": is_holdout_key(model),
            "config_id": config_id,
            "role": role,
            "parameters": params,
            "parameter_observations": counts,
            "parameter_game_counts": {
                parameter: len(bucket["parameter_games"].get(parameter, set()))
                for parameter in params
            },
            "game_count": len(bucket["games"]),
            "game_ids": sorted(bucket["games"]),
            "configuration": dict(bucket["configuration"] or {}),
            "config_signature": config_signature(family, bucket["configuration"] or {}),
            "coarse_config_signature": config_signature(family, bucket["configuration"] or {}, coarse=True),
        })
    return rows


def _quantiles(values: list[float]) -> dict[str, float] | None:
    if len(values) < _MIN_BUCKET:
        return None
    ordered = sorted(values)
    table = {}
    for point in _QUANTILE_POINTS:
        index = min(len(ordered) - 1, max(0, int(round(point * (len(ordered) - 1)))))
        table[f"{point:.2f}"] = ordered[index]
    return table


def _threshold_crossing(curve: dict[float, list[int]], *, ascending: bool = True) -> float | None:
    """Share at which observed acceptance probability crosses one half."""

    usable = sorted((share, hits / total) for share, (hits, total) in curve.items() if total >= 10)
    if len(usable) < 3:
        return None
    if not ascending:
        usable = list(reversed(usable))
    previous = None
    for share, rate in usable:
        if rate >= 0.5:
            if previous is None:
                return share
            prev_share, prev_rate = previous
            if rate == prev_rate:
                return share
            # Linear interpolation between the bracketing bins.
            weight = (0.5 - prev_rate) / (rate - prev_rate)
            return prev_share + weight * (share - prev_share)
        previous = (share, rate)
    return None


def fit_opponent_population(
    data_dir: str | Path = DEFAULT_DATA_DIR,
    output_dir: str | Path = "models/opponent_population",
    *,
    split_mode: str = "none",
    split: str | None = None,
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
    outer_keep: Callable[[dict[str, Any]], bool] | None = None,
    crossfit_manifest: Any = None,
    excluded_fold: int | None = None,
    crossfit_axis: str | None = None,
) -> dict[str, Any]:
    events_path = Path(data_dir) / "processed" / "events.jsonl"
    if not events_path.exists():
        raise FileNotFoundError(f"Missing processed events file: {events_path}")

    barg_shares: dict[tuple[str, str], list[float]] = defaultdict(list)
    barg_concessions: list[float] = []
    barg_curve: dict[str, dict[float, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    neg_prices: dict[tuple[str, str], list[float]] = defaultdict(list)
    neg_concessions: list[float] = []
    neg_curve: dict[str, dict[float, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    pers_truth: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    pers_yes_on_low: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    pers_trust: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    pers_buy_after_no: dict[str, list[int]] = defaultdict(lambda: [0, 0])

    last_share: dict[tuple[str, str], float] = {}
    last_price: dict[tuple[str, str], float] = {}
    scanned = 0

    skipped_by_split = 0
    for event in iter_jsonl(events_path):
        if not keeps(event, mode=split_mode, split=split, holdout_fraction=holdout_fraction):
            skipped_by_split += 1
            continue
        if not _keeps_outer_event(event, outer_keep=outer_keep, crossfit_manifest=crossfit_manifest,
                                  excluded_fold=excluded_fold, crossfit_axis=crossfit_axis):
            skipped_by_split += 1
            continue
        scanned += 1
        family = str(event.get("game_family") or "")
        role = str(event.get("role") or "")
        config = as_dict(event.get("configuration") or event.get("public_parameters"))
        config_id = str(event.get("config_id") or "unknown")
        raw = as_dict(event.get("raw_record"))
        game_role = (str(event.get("game_id")), role)

        if family == "bargaining":
            share = bargaining_offer_self_share(event)
            if share is not None:
                previous = last_share.get(game_role)
                if previous is None:
                    barg_shares[(config_id, role)].append(share)
                else:
                    barg_concessions.append(previous - share)
                last_share[game_role] = share
            elif event.get("action_type") == "decision":
                offer = last_transcript_action(event, "offer")
                money = as_float(config.get("money_to_divide")) or 100.0
                offered = bargaining_share_to_responder(offer or {}, role, money)
                if offered is not None:
                    binned = round(min(1.0, max(0.0, offered)) * 20) / 20
                    accepted = 1 if str(raw.get("decision") or "").lower() == "accept" else 0
                    bucket = barg_curve[f"{config_id}|{role}"][binned]
                    bucket[0] += accepted
                    bucket[1] += 1

        elif family == "negotiation":
            price = negotiation_normalized_price(event)
            if price is not None:
                previous = last_price.get(game_role)
                if previous is None:
                    neg_prices[(config_id, role)].append(price)
                else:
                    neg_concessions.append(previous - price if role == "seller" else price - previous)
                last_price[game_role] = price
            elif event.get("action_type") == "decision":
                offer = last_transcript_action(event, "offer")
                order = as_float(config.get("product_price_order")) or 1_000_000.0
                accepted_price = as_float((offer or {}).get("numeric_action"))
                if accepted_price is None:
                    accepted_price = as_float(as_dict((offer or {}).get("raw")).get("product_price"))
                own = as_float(config.get("seller_value" if role == "seller" else "buyer_value"))
                if accepted_price is not None and own is not None and order > 0:
                    normalized = accepted_price / order
                    margin = normalized - own if role == "seller" else own - normalized
                    binned = round(margin * 20) / 20
                    curve_bucket = neg_curve[f"{config_id}|{role}"][binned]
                    curve_bucket[0] += int(str(raw.get("decision") or "") == "AcceptOffer")
                    curve_bucket[1] += 1

        elif family == "persuasion":
            if role == "seller" and event.get("action_type") in {"recommendation", "message"}:
                quality = persuasion_round_quality(event)
                recommendation = persuasion_recommendation(event) or (raw.get("decision") if raw else None)
                if quality and recommendation in {"yes", "no"}:
                    if quality == "high-quality":
                        bucket = pers_truth[config_id]
                        bucket[0] += int(recommendation == "yes")
                        bucket[1] += 1
                    if quality == "low-quality":
                        low = pers_yes_on_low[config_id]
                        low[0] += int(recommendation == "yes")
                        low[1] += 1
            elif role == "buyer" and event.get("action_type") == "buy_decision":
                seller_item = same_round_transcript_item(event, role="seller")
                recommendation = persuasion_recommendation(seller_item)
                bought = raw.get("decision") or event.get("buy_no_buy")
                if recommendation in {"yes", "no"} and bought in {"yes", "no"}:
                    bucket = pers_trust[config_id] if recommendation == "yes" else pers_buy_after_no[config_id]
                    bucket[0] += int(bought == "yes")
                    bucket[1] += 1

    def _rates(counts: dict[str, list[int]]) -> list[float]:
        return [hits / total for hits, total in counts.values() if total >= 10]

    barg_thresholds = [value for value in (_threshold_crossing(curve) for curve in barg_curve.values()) if value is not None]
    neg_thresholds = [value for value in (_threshold_crossing(curve) for curve in neg_curve.values()) if value is not None]

    families: dict[str, Any] = {
        "bargaining": {
            "target_share": _quantiles([mean(values) for values in barg_shares.values() if values]),
            "concession_rate": _quantiles([value for value in barg_concessions if -0.5 <= value <= 0.5]),
            "accept_threshold": _quantiles(barg_thresholds),
        },
        "negotiation": {
            "aspiration_price": _quantiles([mean(values) for values in neg_prices.values() if values]),
            "concession_rate": _quantiles([value for value in neg_concessions if -0.5 <= value <= 0.5]),
            "accept_margin": _quantiles(neg_thresholds),
        },
        "persuasion": {
            "honesty": _quantiles(_rates(pers_truth)),
            "yes_on_low_rate": _quantiles(_rates(pers_yes_on_low)),
            "trust_prior": _quantiles(_rates(pers_trust)),
            "buy_after_no_rate": _quantiles(_rates(pers_buy_after_no)),
        },
    }

    observations = {
        "bargaining_offer_segments": len(barg_shares),
        "bargaining_concession_observations": len(barg_concessions),
        "bargaining_threshold_segments": len(barg_thresholds),
        "negotiation_offer_segments": len(neg_prices),
        "negotiation_concession_observations": len(neg_concessions),
        "negotiation_threshold_segments": len(neg_thresholds),
        "persuasion_seller_segments": len(pers_truth),
        "persuasion_buyer_segments": len(pers_trust),
    }

    filtered_events = (
        event
        for event in iter_jsonl(events_path)
        if keeps(event, mode=split_mode, split=split, holdout_fraction=holdout_fraction)
        and _keeps_outer_event(event, outer_keep=outer_keep, crossfit_manifest=crossfit_manifest,
                               excluded_fold=excluded_fold, crossfit_axis=crossfit_axis)
    )
    raw_bundles = extract_joint_bundle_observations(filtered_events)
    response_events = (
        event
        for event in iter_jsonl(events_path)
        if keeps(event, mode=split_mode, split=split, holdout_fraction=holdout_fraction)
    )
    response_rows = extract_response_observations(
        response_events,
        outer_keep=outer_keep,
        crossfit_manifest=crossfit_manifest,
        excluded_fold=excluded_fold,
        crossfit_axis=crossfit_axis,
    )
    response_fits = {
        family: fit_hierarchical_responses([row for row in response_rows if row["family"] == family])
        for family in ("bargaining", "negotiation", "persuasion")
    }
    channel_parameters = {
        ("bargaining", "player_1"): (("accept_threshold", "bargaining|player_1"),),
        ("bargaining", "player_2"): (("accept_threshold", "bargaining|player_2"),),
        ("negotiation", "seller"): (("accept_margin", "negotiation|seller"),),
        ("negotiation", "buyer"): (("accept_margin", "negotiation|buyer"),),
        ("persuasion", "seller"): (("honesty", "persuasion|seller_high"), ("yes_on_low_rate", "persuasion|seller_low")),
        ("persuasion", "buyer"): (("trust_prior", "persuasion|buyer_yes"), ("buy_after_no_rate", "persuasion|buyer_no")),
    }
    for row in raw_bundles:
        attached = {}
        for parameter, channel in channel_parameters.get((row["family"], row["role"]), ()):
            value, provenance = response_parameter(
                response_fits[row["family"]], channel=channel,
                player_model=row["player_model"], signature=row["config_signature"],
            )
            attached[parameter] = provenance
            if value is not None:
                row["parameters"][parameter] = value
                support = provenance.get("channel_support") or {}
                row["parameter_observations"][parameter] = int(support.get("rows") or 0)
                row["parameter_game_counts"][parameter] = int(support.get("games") or 0)
        row["response_estimator"] = attached
    parameter_names = {
        ("bargaining", "*"): {"target_share", "concession_rate", "accept_threshold", "action_noise"},
        ("negotiation", "*"): {"aspiration_price", "concession_rate", "accept_margin", "action_noise"},
        ("persuasion", "seller"): {"honesty", "yes_on_low_rate"},
        ("persuasion", "buyer"): {"trust_prior", "buy_after_no_rate"},
    }
    for row in raw_bundles:
        supported = {
            name: value
            for name, value in row["parameters"].items()
            if row["parameter_game_counts"].get(name, 0) >= 2
        }
        row["parameters"] = supported
        row["parameter_observations"] = {name: row["parameter_observations"][name] for name in supported}
        row["parameter_game_counts"] = {name: row["parameter_game_counts"][name] for name in supported}
        expected = parameter_names.get((row["family"], row["role"]), parameter_names.get((row["family"], "*"), set()))
        row["missing_parameters"] = sorted(expected - set(supported))
    retained = [row for row in raw_bundles if len(row["parameters"]) >= 2]
    for family in ("bargaining", "negotiation"):
        noise_values = [row["parameters"]["action_noise"] for row in retained if row["family"] == family and "action_noise" in row["parameters"]]
        families[family]["action_noise"] = _quantiles(noise_values)
    # Score whole bundles using only empirical ranks learned inside this fit
    # partition. Ranking within family+role prevents incomparable role semantics
    # from manufacturing a latent ordering.
    by_cell_parameter: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in retained:
        for parameter, value in row["parameters"].items():
            by_cell_parameter[(row["family"], row["role"], parameter)].append(float(value))
    joint_bundles: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in retained:
        ranks = []
        for parameter, value in sorted(row["parameters"].items()):
            if parameter == "action_noise":
                continue
            reference = sorted(by_cell_parameter[(row["family"], row["role"], parameter)])
            rank = sum(candidate <= float(value) for candidate in reference) / len(reference)
            if parameter in {"concession_rate", "trust_prior"} or (
                parameter == "aspiration_price" and row["role"] == "buyer"
            ):
                rank = 1.0 - rank
            ranks.append(rank)
        score = mean(ranks)
        copied = dict(row)
        copied["latent_score"] = score
        copied["weight"] = max(1, int(row["game_count"]))
        joint_bundles[row["family"]].append(copied)
    for family, bundles in joint_bundles.items():
        by_role: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for bundle in bundles:
            by_role[str(bundle["role"])].append(bundle)
        for role_bundles in by_role.values():
            ordered_role = sorted(role_bundles, key=lambda row: (row["latent_score"], row["bundle_id"]))
            denominator = max(1, len(ordered_role) - 1)
            for index, row in enumerate(ordered_role):
                row["latent_percentile"] = index / denominator
        joint_bundles[family] = sorted(bundles, key=lambda row: (row["role"], row["latent_percentile"], row["bundle_id"]))

    payload = {
        "schema_version": 2,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_dir": str(data_dir),
        "events_scanned": scanned,
        "events_skipped_by_split": skipped_by_split,
        "provenance": split_provenance(split_mode, split, holdout_fraction),
        "min_segment_observations": _MIN_BUCKET,
        "archetype_bands": {name: list(band) for name, band in ARCHETYPE_BANDS.items()},
        "inverted_parameters": sorted(INVERTED_PARAMETERS),
        "observations": observations,
        "families": families,
        "joint_model": {
            "version": 1,
            "method": "configuration_conditioned_empirical_model_config_role_bundle_rank",
            "grouping": ["player_model", "config_id", "role"],
            "minimum_identified_parameters": 2,
            "minimum_distinct_games": 2,
            "latent_score": "equal mean of within-family-role empirical parameter percentiles",
            "inverted_parameters": sorted(INVERTED_PARAMETERS),
            "tie_break": "bundle_id lexical order",
            "draw_ladder": ["exact_config_signature", "coarse_config_signature", "role"],
            "sampling_prior": "distinct-game weighted empirical bundles; archetype label derived after draw",
            "missing_parameter_handling": "explicitly absent; opponent policy uses its existing default",
            "fit_partition_only": True,
            # Full coefficients are required for leak-free OOF decision scoring;
            # summary-only serialization would make the fitted response model
            # impossible to reproduce from the frozen artifact.
            "response_estimators": response_fits,
            "outer_crossfit": {
                "axis": crossfit_axis,
                "excluded_fold": excluded_fold,
                "manifest_supplied": crossfit_manifest is not None,
                "outer_keep_supplied": outer_keep is not None,
            },
        },
        "joint_bundles": dict(joint_bundles),
        "joint_bundle_observations": {
            "raw_segments": len(raw_bundles),
            "retained_segments": len(retained),
            "dropped_below_identification_or_game_support": len(raw_bundles) - len(retained),
            "by_family": {family: len(joint_bundles.get(family, [])) for family in families},
        },
        "notes": [
            "Quantiles are over per-(config_id, role) segment means, not raw actions, so a "
            "single heavily-replayed configuration cannot dominate a band.",
            "Schema-v1 marginal quantiles are retained as an explicit comparator. Schema-v2 "
            "sampling draws one role-compatible empirical parameter bundle, preserving its "
            "within-segment dependence and explicit missingness.",
            "accept_threshold is the interpolated share at which observed acceptance crosses 0.5 "
            "within a segment; segments without a crossing are excluded rather than imputed.",
        ],
    }
    if crossfit_manifest is not None and excluded_fold is not None:
        axis = str(crossfit_axis)
        declared = crossfit_manifest["folds_manifest"][axis][str(excluded_fold)]
        payload["crossfit_provenance"] = {
            "axis": axis,
            "fold": int(excluded_fold),
            "folds": int(crossfit_manifest["axis_folds"][axis]),
            "holdout_fraction": float(crossfit_manifest["axis_holdout_fractions"][axis]),
            "manifest_sha256": crossfit_manifest["manifest_sha256"],
            "training_key_hashes": list(declared["training_key_hashes"]),
            "evaluation_key_hashes": list(declared["evaluation_key_hashes"]),
        }

    out = ensure_dir(output_dir)
    write_json(out / "opponent_population.json", payload)
    missing = [f"{family}.{name}" for family, params in families.items() for name, value in params.items() if value is None]
    if missing:
        payload["unfitted_parameters"] = missing
        write_json(out / "opponent_population.json", payload)
    return payload


class OpponentPopulation:
    """Draws fitted joint bundles, with schema-v1 marginals as compatibility."""

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        self.families = payload.get("families", {})
        self.joint_bundles = payload.get("joint_bundles", {})
        self.bands = {name: tuple(band) for name, band in (payload.get("archetype_bands") or {}).items()}
        self.inverted = set(payload.get("inverted_parameters") or INVERTED_PARAMETERS)

    @classmethod
    def load(cls, path: str | Path | None) -> "OpponentPopulation | None":
        if not path:
            return None
        p = Path(path)
        if p.is_dir():
            p = p / "opponent_population.json"
        if not p.exists():
            return None
        return cls(json.loads(p.read_text(encoding="utf-8")))

    def band(self, archetype: str) -> tuple[float, float]:
        return self.bands.get(archetype, DEFAULT_BAND)

    def sample_bundle(
        self,
        family: str,
        role: str,
        config: dict[str, Any],
        rng: Any,
    ) -> dict[str, Any] | None:
        """Sample the empirical joint population conditional on scenario config."""

        role_bundles = [bundle for bundle in (self.joint_bundles.get(family) or []) if bundle.get("role") == role]
        if not role_bundles:
            return None
        exact = config_signature(family, config)
        coarse = config_signature(family, config, coarse=True)
        eligible = [bundle for bundle in role_bundles if bundle.get("config_signature") == exact]
        level = "exact"
        if not eligible:
            eligible = [bundle for bundle in role_bundles if bundle.get("coarse_config_signature") == coarse]
            level = "coarse"
        if not eligible:
            eligible = role_bundles
            level = "role"
        weights = [max(1, int(bundle.get("weight", 1))) for bundle in eligible]
        selected = dict(rng.choices(eligible, weights=weights, k=1)[0])
        selected["draw_fallback_level"] = level
        percentile = float(selected.get("latent_percentile", 0.5))
        selected["derived_archetype"] = min(
            self.bands or {"historical_imitator": DEFAULT_BAND},
            key=lambda name: abs(percentile - sum(self.band(name)) / 2),
        )
        return selected

    def draw(self, family: str, parameter: str, archetype: str, rng: Any) -> float | None:
        """Sample `parameter` from the archetype's quantile window of real behavior."""

        table = (self.families.get(family) or {}).get(parameter)
        if not table:
            return None
        low, high = self.band(archetype)
        if parameter in self.inverted:
            # A high concession rate or accept margin means a softer opponent, so an
            # aggressive archetype must be read from the low end of the observation.
            low, high = 1.0 - high, 1.0 - low
        point = rng.uniform(low, high)
        key = f"{min(0.99, max(0.01, point)):.2f}"
        if key in table:
            return float(table[key])
        nearest = min(table, key=lambda candidate: abs(float(candidate) - point))
        return float(table[nearest])

    def parameters(
        self,
        family: str,
        archetype: str,
        rng: Any,
        *,
        role: str | None = None,
    ) -> dict[str, Any]:
        # Explicit schema-v1 marginal comparator. Production schema-v2 sampling
        # goes only through sample_bundle(family, role, config, rng).
        drawn: dict[str, float] = {}
        for parameter in sorted((self.families.get(family) or {}).keys()):
            value = self.draw(family, parameter, archetype, rng)
            if value is not None:
                drawn[parameter] = value
        return drawn


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Fit synthetic-opponent parameters to real GLEE behavior.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--output-dir", default="models/opponent_population")
    add_split_arguments(parser)
    args = parser.parse_args(argv)
    payload = fit_opponent_population(
        args.data_dir,
        args.output_dir,
        split_mode=args.split_mode,
        split=args.split,
        holdout_fraction=args.holdout_fraction,
    )
    summary = {
        "events_scanned": payload["events_scanned"],
        "events_skipped_by_split": payload["events_skipped_by_split"],
        "provenance": payload["provenance"],
        "observations": payload["observations"],
        "unfitted_parameters": payload.get("unfitted_parameters", []),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
