FROM golang:1.26-alpine AS cli

ARG SPOGO_VERSION=v0.10.0
ARG SONOSCLI_VERSION=v0.3.4
ARG OPENHUE_VERSION=0.24
ARG TARGETARCH=amd64

RUN CGO_ENABLED=0 go install "github.com/steipete/spogo/cmd/spogo@${SPOGO_VERSION}"
RUN CGO_ENABLED=0 go install "github.com/steipete/sonoscli/cmd/sonos@${SONOSCLI_VERSION}"
RUN set -eux; \
    case "${TARGETARCH}" in \
        amd64) openhue_arch=x86_64; openhue_sha256=b3e0fa9907b0e0450e209a249dc55c99b5fdefc03b0c4f4a4986a2f919a0297f ;; \
        arm64) openhue_arch=arm64; openhue_sha256=412b015634d4bc7295f7b24cb25a5ead5dbade31e3967ad2d57dbfa754a8e4dd ;; \
        *) echo "Unsupported OpenHue architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    wget -O /tmp/openhue.tar.gz \
        "https://github.com/openhue/openhue-cli/releases/download/${OPENHUE_VERSION}/openhue_Linux_${openhue_arch}.tar.gz"; \
    echo "${openhue_sha256}  /tmp/openhue.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/openhue.tar.gz -C /go/bin openhue; \
    rm /tmp/openhue.tar.gz; \
    /go/bin/openhue version

FROM python:3.14-alpine

# Host configs may contain OS-specific absolute paths. Keeping a separate
# container config makes spogo resolve its cookies and cache below the mount.
ENV SPOGO_CONFIG=/workspace/.spogo/container.toml

RUN apk add --no-cache bash curl

COPY --from=cli /go/bin/sonos /usr/local/bin/sonos
COPY --from=cli /go/bin/spogo /usr/local/bin/spogo
COPY --from=cli /go/bin/openhue /usr/local/libexec/openhue
COPY experiments/sandboxing/openhue-env /usr/local/bin/openhue
RUN chmod +x /usr/local/bin/openhue

ENTRYPOINT []
CMD ["bash"]
