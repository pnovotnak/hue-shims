FROM python:3-slim

COPY requirements.txt /opt/hue-shims/requirements.txt
WORKDIR /opt/hue-shims

RUN set -ex; \
  pip install -r requirements.txt

COPY . /opt/hue-shims

ENTRYPOINT ["python", "/opt/hue-shims/shims.py"]
