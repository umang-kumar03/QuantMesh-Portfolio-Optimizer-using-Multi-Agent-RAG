FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml constraints.txt ./
COPY quantmesh ./quantmesh
RUN pip install -c constraints.txt . && useradd --create-home --uid 10001 quantmesh && mkdir /data && chown quantmesh /data
COPY --chmod=0644 app.py ./
COPY --chmod=0644 .streamlit/config.toml ./.streamlit/config.toml
RUN chmod 0755 /app /app/.streamlit
USER quantmesh
ENV QUANTMESH_DEPLOYMENT=production QUANTMESH_AUTH_MODE=multi-user \
    QUANTMESH_DATA_DIR=/data QUANTMESH_DB=/data/research.sqlite3 \
    QUANTMESH_CACHE_DB=/data/market.sqlite3 QUANTMESH_USERS_FILE=/data/users.json \
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"
CMD ["python", "-m", "quantmesh.serve"]
