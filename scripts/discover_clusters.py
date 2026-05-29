"""
Phase 1: Auto-discover naturally crowded tool clusters from MCP-Zero data.

Finds groups of tools where multiple tools have similar names AND similar
descriptions, making description the only differentiator for LLM tool selection.

Then runs a GPT-4o-mini pilot to filter out clusters that are "too easy"
(where the model can already distinguish tools with original descriptions).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections import defaultdict
from datetime import date
from itertools import combinations

from dotenv import load_dotenv
from loguru import logger
from openai import AsyncOpenAI

# ---------------------------------------------------------------------------
# 1. Load data
# ---------------------------------------------------------------------------

DATA_PATH = "data/raw/mcp_zero_servers.jsonl"
OUTPUT_PATH = "data/experiments/clusters.json"


def load_all_tools() -> list[dict]:
    """Load all tools from the MCP-Zero JSONL file."""
    tools: list[dict] = []
    with open(DATA_PATH) as f:
        for line in f:
            server = json.loads(line)
            for tool in server.get("tools", []):
                tools.append(
                    {
                        "tool_id": tool["tool_id"],
                        "server_id": tool["server_id"],
                        "tool_name": tool["tool_name"],
                        "description": tool.get("description", "") or "",
                        "input_schema": tool.get("input_schema"),
                    }
                )
    return tools


# ---------------------------------------------------------------------------
# 2. Verb-prefix grouping
# ---------------------------------------------------------------------------

def extract_verb_prefix(tool_name: str) -> str:
    """Extract the first word (verb) from a tool name split on _ or -."""
    # Normalize: replace - with _, then split
    normalized = tool_name.replace("-", "_")
    parts = normalized.split("_")
    return parts[0].lower() if parts else tool_name.lower()


def group_by_verb(tools: list[dict]) -> dict[str, list[dict]]:
    """Group tools by their verb prefix."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for tool in tools:
        verb = extract_verb_prefix(tool["tool_name"])
        groups[verb].append(tool)
    return groups


# ---------------------------------------------------------------------------
# 3. Description similarity (Jaccard on word tokens)
# ---------------------------------------------------------------------------

STOP_WORDS = frozenset(
    {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "shall",
        "should", "may", "might", "must", "can", "could", "of", "in", "to",
        "for", "with", "on", "at", "from", "by", "about", "as", "into",
        "through", "during", "before", "after", "above", "below", "between",
        "and", "but", "or", "nor", "not", "so", "yet", "both", "either",
        "neither", "each", "every", "all", "any", "few", "more", "most",
        "other", "some", "such", "no", "only", "own", "same", "than", "too",
        "very", "just", "because", "if", "when", "while", "where", "how",
        "what", "which", "who", "whom", "this", "that", "these", "those",
        "it", "its", "they", "them", "their", "we", "our", "you", "your",
        "he", "she", "his", "her",
    }
)


def tokenize(text: str) -> set[str]:
    """Lowercase, remove punctuation, split, remove stop words."""
    text = re.sub(r"[^a-zA-Z0-9\s]", " ", text.lower())
    words = text.split()
    return {w for w in words if w not in STOP_WORDS and len(w) > 1}


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two token sets."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union > 0 else 0.0


def find_similar_description_subgroups(
    tools: list[dict],
    sim_threshold: float = 0.3,
    min_cluster_size: int = 5,
) -> list[list[dict]]:
    """
    Within a verb group, find subgroups where pairwise description similarity
    is above threshold. Uses greedy clustering: start from each tool, grow
    cluster by adding tools with avg similarity > threshold to current cluster.
    Returns clusters with at least min_cluster_size members.
    """
    if len(tools) < min_cluster_size:
        return []

    # Pre-compute token sets
    token_sets = [tokenize(t["description"]) for t in tools]

    # Pre-compute pairwise similarities
    n = len(tools)
    sim_matrix: dict[tuple[int, int], float] = {}
    for i, j in combinations(range(n), 2):
        sim = jaccard_similarity(token_sets[i], token_sets[j])
        sim_matrix[(i, j)] = sim
        sim_matrix[(j, i)] = sim

    # Greedy clustering: find connected components where pairwise sim > threshold
    # Use a graph-based approach: edge exists if sim > threshold
    adjacency: dict[int, set[int]] = defaultdict(set)
    for (i, j), sim in sim_matrix.items():
        if i < j and sim >= sim_threshold:
            adjacency[i].add(j)
            adjacency[j].add(i)

    # Find cliques (or dense subgraphs) using BFS from high-degree nodes
    visited_global: set[int] = set()
    clusters: list[list[dict]] = []

    # Sort nodes by degree (most connected first)
    nodes_by_degree = sorted(range(n), key=lambda x: len(adjacency.get(x, set())), reverse=True)

    for seed in nodes_by_degree:
        if seed in visited_global:
            continue
        if len(adjacency.get(seed, set())) < min_cluster_size - 1:
            continue

        # BFS to find connected component
        component: set[int] = set()
        queue = [seed]
        while queue:
            node = queue.pop(0)
            if node in component:
                continue
            component.add(node)
            for neighbor in adjacency.get(node, set()):
                if neighbor not in component:
                    queue.append(neighbor)

        if len(component) >= min_cluster_size:
            # Verify: compute average pairwise similarity within component
            pairs = list(combinations(sorted(component), 2))
            if pairs:
                avg_sim = sum(sim_matrix.get((i, j), 0.0) for i, j in pairs) / len(pairs)
                if avg_sim >= sim_threshold * 0.5:  # Relaxed: avg sim >= half threshold
                    cluster_tools = [tools[i] for i in sorted(component)]
                    clusters.append(cluster_tools)
                    visited_global.update(component)

    return clusters


# ---------------------------------------------------------------------------
# 4. Filter name-distinguishable clusters
# ---------------------------------------------------------------------------

def is_name_distinguishable(cluster: list[dict]) -> bool:
    """
    Return True if >50% of tool names contain a unique server_id prefix,
    making them distinguishable by name alone.
    """
    # Check if tool names contain their server_id as a substring
    count_with_server_prefix = 0
    for tool in cluster:
        name_lower = tool["tool_name"].lower().replace("-", "_")
        server_lower = tool["server_id"].lower().replace("-", "_")
        # Check if server_id appears in the tool_name
        if server_lower in name_lower:
            count_with_server_prefix += 1

    if count_with_server_prefix / len(cluster) > 0.5:
        return True

    # Also check: if all tool names share the same prefix pattern beyond the verb,
    # they might be from different servers but the second word distinguishes them
    # e.g., "search_slack", "search_github" — the second word is unique
    second_words: list[str] = []
    for tool in cluster:
        normalized = tool["tool_name"].replace("-", "_")
        parts = normalized.split("_")
        if len(parts) > 1:
            second_words.append(parts[1].lower())
        else:
            second_words.append("")

    # If most second words are unique AND match server names, it's distinguishable
    unique_seconds = set(second_words)
    server_ids = {t["server_id"].lower().replace("-", "_").split("_")[0] for t in cluster}

    # If second words overlap significantly with server IDs
    overlap = unique_seconds & server_ids
    if len(overlap) / max(len(unique_seconds), 1) > 0.5:
        return True

    return False


# ---------------------------------------------------------------------------
# 5. Select target tool (most generic/vague description)
# ---------------------------------------------------------------------------

def select_target_tool(cluster: list[dict]) -> dict:
    """
    Select the tool with the most generic/vague description.
    Heuristic: shortest description with fewest unique/specific words.
    """
    scored: list[tuple[float, dict]] = []
    for tool in cluster:
        desc = tool["description"]
        tokens = tokenize(desc)
        # Vagueness score: fewer tokens = more vague, shorter = more vague
        # Also penalize descriptions that contain very specific terms
        specificity = len(tokens)
        length = len(desc)
        # Lower score = more generic
        score = specificity * 2 + length * 0.01
        scored.append((score, tool))

    scored.sort(key=lambda x: x[0])
    return scored[0][1]


# ---------------------------------------------------------------------------
# 6. GPT-4o-mini pilot validation
# ---------------------------------------------------------------------------

async def pilot_validate_cluster(
    client: AsyncOpenAI,
    cluster: list[dict],
    target_tool: dict,
    n_reps: int = 2,
) -> float:
    """
    Run pilot validation: present tools as function choices, ask GPT to pick one
    for a generic query. Returns hit rate (fraction of times target was chosen).
    """
    # Build a generic query based on the verb prefix (no product/service names)
    verb = extract_verb_prefix(target_tool["tool_name"])
    # Create a generic functional query
    query = _build_generic_query(verb, cluster)

    # Build function definitions
    functions = []
    for tool in cluster[:8]:  # Limit to 8 tools max for context
        func_def = {
            "type": "function",
            "function": {
                "name": tool["tool_id"].replace("::", "__"),
                "description": tool["description"][:500] if tool["description"] else "No description",
                "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
            },
        }
        functions.append(func_def)

    target_func_name = target_tool["tool_id"].replace("::", "__")
    hits = 0

    for rep in range(n_reps):
        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a helpful assistant. When asked to perform a task, "
                            "select the most appropriate tool from the available functions. "
                            "You MUST call exactly one function."
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                tools=functions,
                tool_choice="required",
                temperature=0.0,
                max_tokens=256,
            )

            # Check which tool was called
            if response.choices and response.choices[0].message.tool_calls:
                called = response.choices[0].message.tool_calls[0].function.name
                if called == target_func_name:
                    hits += 1
        except Exception as e:
            logger.warning(f"Pilot call failed (rep {rep}): {e}")

    return hits / n_reps if n_reps > 0 else 0.0


def _build_generic_query(verb: str, cluster: list[dict]) -> str:
    """Build a generic functional query without product/service names."""
    # Extract common description themes
    all_tokens: list[str] = []
    for tool in cluster:
        all_tokens.extend(tokenize(tool["description"]))

    # Find most common content words
    from collections import Counter
    word_counts = Counter(all_tokens)
    common_words = [w for w, _ in word_counts.most_common(5)]

    # Map common verbs to natural queries
    verb_queries = {
        "search": "Search for information about {}",
        "get": "Retrieve the {} data I need",
        "list": "Show me a list of available {}",
        "create": "Create a new {} for me",
        "delete": "Delete the specified {}",
        "update": "Update the existing {} with new values",
        "send": "Send a {} to the recipient",
        "read": "Read the contents of the {}",
        "write": "Write data to the {}",
        "run": "Run the {} operation",
        "execute": "Execute the {} command",
        "fetch": "Fetch the latest {} information",
        "find": "Find the {} that matches my criteria",
        "query": "Query the database for {}",
        "add": "Add a new {} to the collection",
        "remove": "Remove the {} from the system",
        "set": "Set the {} configuration value",
        "check": "Check the status of {}",
        "start": "Start the {} process",
        "stop": "Stop the running {}",
    }

    topic = " ".join(common_words[:3]) if common_words else "items"

    if verb in verb_queries:
        return verb_queries[verb].format(topic)
    else:
        return f"I need to {verb} some {topic}"


# ---------------------------------------------------------------------------
# 7. Main pipeline
# ---------------------------------------------------------------------------

async def main() -> None:
    load_dotenv()

    logger.info("Loading tools from MCP-Zero data...")
    all_tools = load_all_tools()
    logger.info(f"Loaded {len(all_tools)} tools from {DATA_PATH}")

    # Step 1: Group by verb prefix
    verb_groups = group_by_verb(all_tools)
    logger.info(f"Found {len(verb_groups)} verb prefix groups")

    # Show top verb groups by size
    sorted_groups = sorted(verb_groups.items(), key=lambda x: len(x[1]), reverse=True)
    logger.info("Top 15 verb groups:")
    for verb, tools in sorted_groups[:15]:
        logger.info(f"  {verb}: {len(tools)} tools")

    # Step 2: Find description-similar subgroups within each verb group
    logger.info("\nFinding description-similar subgroups (Jaccard >= 0.3, min 5 tools)...")
    candidate_clusters: list[dict] = []
    cluster_id_counter = 0

    for verb, tools in sorted_groups:
        if len(tools) < 5:
            continue

        subgroups = find_similar_description_subgroups(tools, sim_threshold=0.3, min_cluster_size=5)

        for subgroup in subgroups:
            cluster_id_counter += 1
            # Check if name-distinguishable
            if is_name_distinguishable(subgroup):
                logger.info(
                    f"  SKIP (name-distinguishable): verb={verb}, "
                    f"size={len(subgroup)}, "
                    f"names={[t['tool_name'] for t in subgroup[:3]]}..."
                )
                continue

            target = select_target_tool(subgroup)

            cluster_info = {
                "cluster_id": f"{verb}_{cluster_id_counter:03d}",
                "verb_prefix": verb,
                "size": len(subgroup),
                "tools": [
                    {
                        "tool_id": t["tool_id"],
                        "name": t["tool_name"],
                        "desc": t["description"][:200],
                    }
                    for t in subgroup
                ],
                "target_tool_id": target["tool_id"],
                "target_tool_name": target["tool_name"],
                "target_desc": target["description"][:200],
            }
            candidate_clusters.append(cluster_info)
            logger.info(
                f"  CANDIDATE: {cluster_info['cluster_id']} "
                f"(size={len(subgroup)}, target={target['tool_name']})"
            )
            for t in subgroup[:5]:
                logger.info(f"    - {t['tool_id']}: {t['description'][:80]}")

    logger.info(f"\nTotal candidate clusters: {len(candidate_clusters)}")

    # Step 3: GPT-4o-mini pilot validation
    logger.info("\n--- GPT-4o-mini Pilot Validation ---")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY not found in environment. Skipping pilot.")
        pilot_results = []
        final_clusters = candidate_clusters
    else:
        client = AsyncOpenAI(api_key=api_key)
        pilot_results = []
        final_clusters = []

        # Rebuild full tool data for pilot (need full descriptions)
        tool_lookup = {t["tool_id"]: t for t in all_tools}

        for cluster_info in candidate_clusters:
            cluster_tools = [
                tool_lookup[t["tool_id"]]
                for t in cluster_info["tools"]
                if t["tool_id"] in tool_lookup
            ]
            target_tool = tool_lookup.get(cluster_info["target_tool_id"])

            if not target_tool or len(cluster_tools) < 3:
                logger.warning(f"Skipping {cluster_info['cluster_id']}: insufficient tools")
                continue

            # Run pilot (2 reps)
            hit_rate = await pilot_validate_cluster(
                client, cluster_tools, target_tool, n_reps=2
            )

            pilot_result = {
                "cluster_id": cluster_info["cluster_id"],
                "target_tool_id": cluster_info["target_tool_id"],
                "v_orig_hit_rate": hit_rate,
                "verdict": "TOO_EASY" if hit_rate > 0.8 else "KEEP",
            }
            pilot_results.append(pilot_result)

            logger.info(
                f"  Pilot {cluster_info['cluster_id']}: "
                f"hit_rate={hit_rate:.1%} -> {pilot_result['verdict']}"
            )

            if hit_rate <= 0.8:
                final_cluster = {
                    **cluster_info,
                    "pilot_v_orig_hit_rate": hit_rate,
                    "reason": (
                        f"{len(cluster_tools)} tools all describe '{cluster_info['verb_prefix']}' operations, "
                        f"names are generic, GPT hit rate {hit_rate:.0%} with original descriptions"
                    ),
                }
                final_clusters.append(final_cluster)

    logger.info(f"\nFinal clusters after pilot filter: {len(final_clusters)}")

    # Step 4: If we don't have 10+ clusters, relax thresholds and try again
    if len(final_clusters) < 10 and len(candidate_clusters) < 15:
        logger.info("\nNot enough clusters. Re-running with relaxed thresholds (Jaccard >= 0.2, min 4 tools)...")
        candidate_clusters_relaxed: list[dict] = []
        existing_tool_ids = set()
        for c in candidate_clusters:
            for t in c["tools"]:
                existing_tool_ids.add(t["tool_id"])

        cluster_id_counter_r = 100
        for verb, tools in sorted_groups:
            if len(tools) < 4:
                continue

            subgroups = find_similar_description_subgroups(
                tools, sim_threshold=0.2, min_cluster_size=4
            )

            for subgroup in subgroups:
                # Skip if significant overlap with existing clusters
                subgroup_ids = {t["tool_id"] for t in subgroup}
                if len(subgroup_ids & existing_tool_ids) > len(subgroup) * 0.5:
                    continue

                cluster_id_counter_r += 1
                if is_name_distinguishable(subgroup):
                    continue

                target = select_target_tool(subgroup)
                cluster_info = {
                    "cluster_id": f"{verb}_r{cluster_id_counter_r:03d}",
                    "verb_prefix": verb,
                    "size": len(subgroup),
                    "tools": [
                        {
                            "tool_id": t["tool_id"],
                            "name": t["tool_name"],
                            "desc": t["description"][:200],
                        }
                        for t in subgroup
                    ],
                    "target_tool_id": target["tool_id"],
                    "target_tool_name": target["tool_name"],
                    "target_desc": target["description"][:200],
                }
                candidate_clusters_relaxed.append(cluster_info)
                logger.info(
                    f"  RELAXED CANDIDATE: {cluster_info['cluster_id']} "
                    f"(size={len(subgroup)}, target={target['tool_name']})"
                )

        # Pilot the relaxed candidates too
        if api_key and candidate_clusters_relaxed:
            for cluster_info in candidate_clusters_relaxed:
                cluster_tools = [
                    tool_lookup[t["tool_id"]]
                    for t in cluster_info["tools"]
                    if t["tool_id"] in tool_lookup
                ]
                target_tool = tool_lookup.get(cluster_info["target_tool_id"])
                if not target_tool or len(cluster_tools) < 3:
                    continue

                hit_rate = await pilot_validate_cluster(
                    client, cluster_tools, target_tool, n_reps=2
                )

                pilot_result = {
                    "cluster_id": cluster_info["cluster_id"],
                    "target_tool_id": cluster_info["target_tool_id"],
                    "v_orig_hit_rate": hit_rate,
                    "verdict": "TOO_EASY" if hit_rate > 0.8 else "KEEP",
                }
                pilot_results.append(pilot_result)

                logger.info(
                    f"  Relaxed Pilot {cluster_info['cluster_id']}: "
                    f"hit_rate={hit_rate:.1%} -> {pilot_result['verdict']}"
                )

                if hit_rate <= 0.8:
                    final_cluster = {
                        **cluster_info,
                        "pilot_v_orig_hit_rate": hit_rate,
                        "reason": (
                            f"{len(cluster_tools)} tools describe '{cluster_info['verb_prefix']}' operations, "
                            f"names are generic, GPT hit rate {hit_rate:.0%}"
                        ),
                    }
                    final_clusters.append(final_cluster)

            candidate_clusters.extend(candidate_clusters_relaxed)

    # Step 5: Write output
    output = {
        "discovery_date": str(date.today()),
        "total_tools_scanned": len(all_tools),
        "algorithm": {
            "verb_prefix_grouping": True,
            "description_similarity": "jaccard",
            "primary_threshold": 0.3,
            "relaxed_threshold": 0.2,
            "min_cluster_size_primary": 5,
            "min_cluster_size_relaxed": 4,
            "name_distinguishability_filter": ">50% tools contain server_id in name",
            "pilot_model": "gpt-4o-mini",
            "pilot_reps": 2,
            "pilot_exclusion": ">80% hit rate with V_orig",
        },
        "candidate_clusters": candidate_clusters,
        "pilot_results": pilot_results,
        "final_clusters": final_clusters,
        "summary": {
            "total_candidates": len(candidate_clusters),
            "pilot_tested": len(pilot_results),
            "final_count": len(final_clusters),
            "target_met": len(final_clusters) >= 10,
        },
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    logger.info(f"\nResults written to {OUTPUT_PATH}")
    logger.info(f"Summary: {len(candidate_clusters)} candidates -> {len(final_clusters)} final clusters")

    if len(final_clusters) >= 10:
        logger.info("TARGET MET: 10+ crowded clusters discovered!")
    else:
        logger.warning(
            f"Target not met: only {len(final_clusters)} clusters. "
            "Consider manual review of candidates or further threshold tuning."
        )


if __name__ == "__main__":
    asyncio.run(main())
