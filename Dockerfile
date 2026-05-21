FROM python:3.12-slim AS build

ENV POETRY_VERSION=2.1.3 \
    POETRY_VIRTUALENVS_CREATE=false \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN pip install "poetry==${POETRY_VERSION}"

COPY pyproject.toml README.md ./
COPY src ./src
RUN poetry build --format wheel

FROM python:3.12-slim AS runtime

ENV PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY --from=build /app/dist/*.whl /tmp/
RUN pip install /tmp/*.whl && rm /tmp/*.whl

COPY profiles ./profiles
COPY plans ./plans

EXPOSE 5050

ENTRYPOINT ["mfg-ctl"]
CMD ["--help"]
