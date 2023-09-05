FROM python:3.8-alpine3.17


WORKDIR /app
COPY . /app

RUN apk add gcc musl-dev libffi-dev git
RUN python3 -m pip install poetry
RUN poetry install

ENTRYPOINT [ "poetry", "run", "python", "-m", "fatcat_server.__main__" ]