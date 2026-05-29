ARG ARCH=x86_64
FROM --platform=linux/amd64 public.ecr.aws/lambda/python:3.12-${ARCH}

COPY service/lambdas/search/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

ENV HF_HOME=/var/task/.cache/fastembed
RUN python -c "from fastembed import SparseTextEmbedding; SparseTextEmbedding(model_name='prithivida/Splade_PP_en_v1')"

# Lay out the task root to mirror the Zip build artifact (service/build/build.py):
#   /var/task/handler.py          -> Lambda entry
#   /var/task/mcp_discovery/      -> core library (from src/)
#   /var/task/service/            -> runtime packages (adapters, services, shared, ...)
COPY service/lambdas/search/handler.py /var/task/handler.py
COPY src/mcp_discovery/ /var/task/mcp_discovery/
COPY service/ /var/task/service/

CMD ["handler.lambda_handler"]
