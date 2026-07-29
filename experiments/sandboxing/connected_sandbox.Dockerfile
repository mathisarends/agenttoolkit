FROM golang:1.26-alpine AS cli

ARG SPOGO_VERSION=v0.10.0
ARG SONOSCLI_VERSION=v0.3.4

RUN CGO_ENABLED=0 go install "github.com/steipete/spogo/cmd/spogo@${SPOGO_VERSION}"
RUN CGO_ENABLED=0 go install "github.com/steipete/sonoscli/cmd/sonos@${SONOSCLI_VERSION}"

FROM python:3.14-alpine

# Host configs may contain OS-specific absolute paths. Keeping a separate
# container config makes spogo resolve its cookies and cache below the mount.
ENV SPOGO_CONFIG=/workspace/.spogo/container.toml

RUN apk add --no-cache bash curl
RUN pip install --no-cache-dir "hueify[cli]"

COPY --from=cli /go/bin/sonos /usr/local/bin/sonos
COPY --from=cli /go/bin/spogo /usr/local/bin/spogo

ENTRYPOINT []
CMD ["bash"]
