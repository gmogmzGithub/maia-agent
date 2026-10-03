FROM dxflrs/garage:v2.3.0 AS garage

FROM alpine:3.22

RUN apk add --no-cache ca-certificates curl

COPY --from=garage /garage /garage
COPY docker/garage-entrypoint.sh /usr/local/bin/garage-entrypoint

RUN chmod 0755 /usr/local/bin/garage-entrypoint

ENTRYPOINT ["/usr/local/bin/garage-entrypoint"]
