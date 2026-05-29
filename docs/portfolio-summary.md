# Portfolio Summary

## One-Line Summary

MCP Discovery Platform reframes MCP tool selection as a retrieval/control-plane problem: search the right tool candidates first, then let the LLM choose from a small, explainable, operationally safer set.

## What Was Built

- A Python retrieval library with Flat, Sequential, and Parallel strategy implementations.
- A serverless backend using AWS Lambda, API Gateway, SAM, Qdrant, and Supabase.
- A hybrid retrieval path using OpenAI dense embeddings, FastEmbed SPLADE sparse vectors, and Qdrant RRF.
- A provider-facing React/Vite dashboard.
- An experiment pipeline with tracked metrics, ADRs, and reproducible result artifacts.

## Main Engineering Decisions

- Moved away from prompt-only tool selection because prompt-bloat and tool confusion scale poorly.
- Moved away from synthetic-only GT after finding ambiguity and alternative-tool gaps.
- Changed the North Star from P@1 to Recall@K when the product contract became "return a useful candidate set to the LLM."
- Kept the hosted path simpler than the early parallel-reranking experiment path because the larger Recall@K regime favored Flat hybrid retrieval.
- Used Lambda container images only where SPLADE size required them, keeping the rest of the fleet zip-style.

## Interview Talking Points

- The interesting work is not just building a search endpoint; it is converting a tool-choice problem into measurable retrieval architecture.
- Early experiments supported a Parallel/RRF + reranker story, but larger GT changed the conclusion. The project keeps that pivot visible instead of hiding it.
- The system separates query path, indexing path, and execution path so failures in one lane do not automatically break the others.
- Operability signals are treated as execution reliability signals, not popularity ranking signals.
