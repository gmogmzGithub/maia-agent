FROM golang:1.24-alpine AS build
ARG MINIO_RELEASE=RELEASE.2025-06-13T11-33-47Z

RUN apk add --no-cache git
WORKDIR /src
RUN git clone --depth 1 --branch "$MINIO_RELEASE" https://github.com/minio/minio.git . \
    && CGO_ENABLED=0 go build -tags kqueue -trimpath -o /minio .

FROM alpine:3.22

RUN apk add --no-cache ca-certificates curl
COPY --from=build /minio /usr/local/bin/minio

ENTRYPOINT ["/usr/local/bin/minio"]
