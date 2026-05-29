# External Datasets

> 이 디렉토리의 데이터는 .gitignored입니다. 아래 지침에 따라 수동으로 다운로드하세요.
> 로컬 canonical contract는 `data/external/mcp-zero/servers.json` + `data/external/mcp-atlas/*.parquet` 입니다.

## MCP-Zero (Tool Pool 확장용)

- **논문**: https://arxiv.org/abs/2506.01056
- **GitHub**: https://github.com/xfey/MCP-Zero
- **데이터**: 308 servers, 2,797 tools, text-embedding-3-large 벡터 포함
- **다운로드**: GitHub README의 Google Drive 링크 → JSON
- **로컬 canonical 파일명**: upstream 파일명이 `mcp_tools_with_embedding.json`이어도 repo에서는 `servers.json`으로 맞춰 둡니다.
- **저장 위치**: `data/external/mcp-zero/`
- **라이선스**: upstream README 기준 MIT. 사용 전 다시 확인 권장.

```bash
# 다운로드 후 예상 구조:
data/external/mcp-zero/
└── servers.json           # repo-local canonical filename
```

## MCP-Atlas (Ground Truth 대체용)

- **논문**: https://arxiv.org/abs/2602.00933 (Scale AI)
- **HuggingFace**: https://huggingface.co/datasets/ScaleAI/MCP-Atlas
- **데이터**: 500 human-authored tasks, 36 servers, 307 tools
- **다운로드**: HuggingFace CLI 또는 웹에서 parquet 다운로드
- **저장 위치**: `data/external/mcp-atlas/`
- **라이선스**: Scale AI 학술 라이선스 확인 필요

```bash
# HuggingFace CLI로 다운로드:
pip install huggingface_hub
huggingface-cli download ScaleAI/MCP-Atlas --local-dir data/external/mcp-atlas/

# 다운로드 후 예상 구조:
data/external/mcp-atlas/
└── *.parquet              # 500 human-authored tasks
```

## 변환 스크립트

```bash
# MCP-Zero → MCPServer/MCPTool + Qdrant 인덱싱
uv run python scripts/import_mcp_zero.py --input data/external/mcp-zero/servers.json

# MCP-Atlas parquet → GT JSONL
uv run python scripts/convert_mcp_atlas.py --dry-run   # 검사만
uv run python scripts/convert_mcp_atlas.py              # LLM query 생성 포함 (ADR-0012 per-step 분해)
```
