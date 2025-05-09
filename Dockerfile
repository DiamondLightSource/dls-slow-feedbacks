# The devcontainer should use the developer target and run as root with podman
# or docker with user namespaces.
ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION} AS build

# Add any system dependencies for the developer/build environment here
RUN apt-get update && apt-get install -y --no-install-recommends \
    graphviz \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /dls_slow_feedbacks
COPY . /dls_slow_feedbacks/

# Set up a virtual environment and put it in PATH
RUN python -m venv /venv
RUN pip install ./

ENV PATH=/venv/bin:$PATH
ENV EPICS_CA_SERVER_PORT=8064
ENV EPICS_CA_REPEATER_PORT=8065

CMD ["start-ioc"]
