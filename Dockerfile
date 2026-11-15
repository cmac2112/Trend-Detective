# Trend Detective: the web app and its API in one container, on one address.
# Used by Render (render.yaml); works with any Docker host.
#
# Build from the REPOSITORY ROOT (the API installs ../PythonPoc, so it needs both folders):
#   docker build -t trend-detective .
# Run locally (secrets come from the environment, never from a file baked into the image):
#   docker run --rm -p 8000:8000 -e EARTHDATA_TOKEN -e ANTHROPIC_API_KEY -e ADMIN_TOKEN trend-detective
#   then open http://localhost:8000
#
# The starter examples' data (PythonPoc/data/tiles, ~34 MB) is in git and copied in, so the
# examples load instantly. Other regions stream from NASA's cloud (needs EARTHDATA_TOKEN).

# ---- stage 1: build the React client --------------------------------------------------
FROM node:22-slim AS client
WORKDIR /client
COPY client/package.json client/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY client/ ./
# "sameorigin" mode: the client calls the API on the address the page came from.
RUN npm run build -- --mode sameorigin

# ---- stage 2: the API, serving the built client at "/" ---------------------------------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLBACKEND=Agg \
    EARTHTRENDS_DATA_DIR=/app/PythonPoc/data \
    EARTHDATA_ALLOW_PASSWORD=0 \
    CLIENT_DIST_DIR=/app/client/dist \
    PORT=8000

# Trust X-Forwarded-For from the host's proxy (Render, Azure) so rate limits and the admin
# check see each caller's real address. Safe only while the container is reachable through
# that proxy alone. (Set here, not as a CLI "*", which a shell would expand into file names.)
ENV FORWARDED_ALLOW_IPS="*"

WORKDIR /app

# 1. Dependencies first, so code changes don't reinstall them (better layer caching).
#    The API's requirements.txt installs ../PythonPoc with `-e`; that line is dropped here
#    and the library is installed from its own folder in step 2. Test-only packages are skipped.
#    constraints.txt pins every package to the version the tests passed with. Regenerate it
#    after upgrading anything (from the repo root, PowerShell):
#      TrendApi\.venv\Scripts\python -m pip list --format=freeze --exclude-editable > constraints.txt
#    (then drop pip, setuptools, wheel and pywin32 lines).
COPY constraints.txt ./
COPY PythonPoc/pyproject.toml PythonPoc/requirements.txt PythonPoc/
COPY TrendApi/requirements.txt TrendApi/
RUN grep -vE '^\s*(-e|pytest)' TrendApi/requirements.txt > /tmp/api-req.txt \
 && grep -vE '^\s*pytest' PythonPoc/requirements.txt > /tmp/core-req.txt \
 && pip install -c constraints.txt -r /tmp/core-req.txt -r /tmp/api-req.txt

# 2. The code. The repo layout is kept (/app/PythonPoc, /app/TrendApi) because the API
#    finds the library's examples and data relative to itself.
COPY PythonPoc/earthtrends PythonPoc/earthtrends
COPY PythonPoc/examples PythonPoc/examples
COPY TrendApi/app TrendApi/app
RUN pip install --no-deps -e PythonPoc
COPY --from=client /client/dist client/dist

# 3. Demo data: the starter examples' tiles. Owned by the app user, which caches NASA's grid
#    files (and the ozone file, on first use) there at runtime.
RUN useradd --create-home --uid 10001 app
COPY --chown=app:app PythonPoc/data PythonPoc/data
USER app

WORKDIR /app/TrendApi
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'), timeout=4).status == 200 else 1)"

# ONE worker on purpose: background jobs, the result cache and rate-limit counters live in
# memory, so every request has to reach the same process. Scale up (more RAM), not out.
# The port comes from $PORT (Render sets it); `exec` makes uvicorn receive stop signals.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"$PORT\" --workers 1 --proxy-headers"]
