# Read the doc: https://huggingface.co/docs/hub/spaces-sdks-docker
# you will also find guides on how best to write your Dockerfile

# 3.10+ required: the MCP SDK does not support 3.9.
FROM python:3.12

RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /app

COPY --chown=user ./requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY --chown=user . /app

# Compile the crossword word bank into SQLite at build time so the first request
# doesn't pay for it. The database is generated, never committed, never served.
RUN python build_wordbank.py

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
