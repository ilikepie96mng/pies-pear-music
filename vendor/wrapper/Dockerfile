FROM docker.io/library/debian:stable-slim

ENV args=""

COPY ./rootfs /app/rootfs
COPY ./wrapper /app
WORKDIR /app

CMD ["bash", "-c", "exec /app/wrapper $args"]

EXPOSE 10020 20020 30020
