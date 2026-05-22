FROM alpine:3.20 AS tools
RUN apk add --no-cache busybox-static

FROM otel/opentelemetry-collector-contrib:0.123.0
COPY --from=tools /bin/busybox.static /usr/local/bin/busybox.static
