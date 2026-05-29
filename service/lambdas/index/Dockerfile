ARG ARCH=x86_64
FROM --platform=linux/amd64 public.ecr.aws/lambda/python:3.12-${ARCH}

COPY service/lambdas/index/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

ENV HF_HOME=/var/task/.cache/fastembed
RUN python -c "from fastembed import SparseTextEmbedding; SparseTextEmbedding(model_name='prithivida/Splade_PP_en_v1')"

# Mirror the Zip build layout (service/build/build.py).
COPY service/lambdas/index/handler.py /var/task/handler.py
COPY src/mcp_discovery/ /var/task/mcp_discovery/
COPY service/ /var/task/service/

CMD ["handler.lambda_handler"]
