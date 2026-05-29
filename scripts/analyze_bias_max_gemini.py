import argparse
import json
import math
from pathlib import Path

from loguru import logger
from scipy.stats import proportions_ztest

DEFAULT_INPUT = "data/experiments/bias_max_gemini_results.json"
DEFAULT_OUTPUT = "data/experiments/bias_max_gemini_statistics.json"

ALPHA_BONFERRONI = 0.05 / 3  # 0.01667

CONFIRMED_HYPOTHESES = [
    ("H1", "V_spec", "V_prose"),
    ("H2", "V_md", "V_prose"),
    ("H3", "V_spec", "V_orig"),
]
EXPLORATORY = [("exploratory", "V_xml", "V_prose")]


def cohen_h(p1: float, p2: float) -> float:
    return 2 * math.asin(math.sqrt(p1)) - 2 * math.asin(math.sqrt(p2))


def aggregate_hits(
    data: dict, variant: str
) -> tuple[int, int]:
    hits = 0
    total = 0
    for cluster_results in data.values():
        reps = cluster_results.get(variant, {})
        for query_reps in reps.values():
            hits += sum(query_reps)
            total += len(query_reps)
    return hits, total


def cluster_hit_rate(data: dict, variant: str, cluster_id: str) -> float:
    cluster = data.get(cluster_id, {})
    reps = cluster.get(variant, {})
    hits = 0
    total = 0
    for query_reps in reps.values():
        hits += sum(query_reps)
        total += len(query_reps)
    return hits / total if total > 0 else 0.0


def run_test(
    data: dict,
    variant_a: str,
    variant_b: str,
    bonferroni_corrected: bool,
) -> dict:
    hits_a, n_a = aggregate_hits(data, variant_a)
    hits_b, n_b = aggregate_hits(data, variant_b)

    rate_a = hits_a / n_a if n_a > 0 else 0.0
    rate_b = hits_b / n_b if n_b > 0 else 0.0

    count = [hits_a, hits_b]
    nobs = [n_a, n_b]
    z_stat, p_raw = proportions_ztest(count, nobs)

    p_bonferroni = p_raw * 3 if bonferroni_corrected else p_raw
    p_bonferroni = min(p_bonferroni, 1.0) if bonferroni_corrected else p_bonferroni
    alpha = ALPHA_BONFERRONI if bonferroni_corrected else None
    sig = bool(p_bonferroni < ALPHA_BONFERRONI) if bonferroni_corrected else None

    h = cohen_h(rate_a, rate_b)

    key = f"{variant_a}_vs_{variant_b}"
    return {
        key: {
            "hits_a": hits_a,
            "n_a": n_a,
            "hits_b": hits_b,
            "n_b": n_b,
            "rate_a": rate_a,
            "rate_b": rate_b,
            "diff": rate_a - rate_b,
            "z": float(z_stat),
            "p_raw": float(p_raw),
            "p_bonferroni": float(p_bonferroni),
            "cohen_h": float(h),
            "alpha_bonferroni": alpha,
            "sig": sig,
        }
    }


def compute_overall(data: dict, variants: list[str]) -> dict[str, float]:
    result = {}
    for v in variants:
        hits, total = aggregate_hits(data, v)
        result[v] = hits / total if total > 0 else 0.0
    return result


def compute_cluster_breakdown(data: dict, variants: list[str]) -> dict:
    breakdown = {}
    for cluster_id in data:
        breakdown[cluster_id] = {v: cluster_hit_rate(data, v, cluster_id) for v in variants}
    return breakdown


def print_markdown_table(stats: dict) -> None:
    print("\n## Overall Hit Rates\n")
    print("| Variant | Hit Rate |")
    print("|---------|----------|")
    for v, r in stats["overall"].items():
        print(f"| {v} | {r:.4f} |")

    print("\n## Hypothesis Tests\n")
    print("| Hypothesis | Contrast | rate_a | rate_b | diff | z | p_raw | p_bonf | cohen_h | sig |")
    print("|------------|----------|--------|--------|------|---|-------|--------|---------|-----|")

    for section in ["H1", "H2", "H3"]:
        for contrast, result in stats[section].items():
            print(
                f"| {section} | {contrast} | {result['rate_a']:.4f} | {result['rate_b']:.4f} | "
                f"{result['diff']:+.4f} | {result['z']:.3f} | {result['p_raw']:.4f} | "
                f"{result['p_bonferroni']:.4f} | {result['cohen_h']:+.4f} | {result['sig']} |"
            )

    for contrast, result in stats["exploratory"].items():
        print(
            f"| exploratory | {contrast} | {result['rate_a']:.4f} | {result['rate_b']:.4f} | "
            f"{result['diff']:+.4f} | {result['z']:.3f} | {result['p_raw']:.4f} | "
            f"N/A | {result['cohen_h']:+.4f} | N/A |"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Statistical analysis of bias_max_gemini experiment"
    )
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Path to results JSON")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Path for output statistics JSON")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    logger.info(f"Loading results from {input_path}")
    with input_path.open() as f:
        data: dict = json.load(f)

    all_variants = ["V_orig", "V_prose", "V_spec", "V_md", "V_xml"]

    overall = compute_overall(data, all_variants)
    logger.info(f"Overall hit rates: {overall}")

    stats: dict = {"overall": overall}

    for label, va, vb in CONFIRMED_HYPOTHESES:
        logger.info(f"Running {label}: {va} vs {vb}")
        stats[label] = run_test(data, va, vb, bonferroni_corrected=True)

    exploratory_results: dict = {}
    for _, va, vb in EXPLORATORY:
        logger.info(f"Running exploratory: {va} vs {vb}")
        result = run_test(data, va, vb, bonferroni_corrected=False)
        exploratory_results.update(result)
    stats["exploratory"] = exploratory_results

    stats["cluster_breakdown"] = compute_cluster_breakdown(data, all_variants)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        json.dump(stats, f, indent=2)
    logger.info(f"Statistics written to {output_path}")

    print_markdown_table(stats)


if __name__ == "__main__":
    main()
