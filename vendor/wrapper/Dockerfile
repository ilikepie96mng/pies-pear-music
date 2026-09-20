FROM docker.io/library/debian:stable-slim

ENV args=""

COPY ./rootfs /app/rootfs
COPY ./wrapper /app
WORKDIR /app

CMD ["bash", "-c", "read -r -t 3 LOGIN_ARGS || LOGIN_ARGS=\"\"; exec /app/wrapper $LOGIN_ARGS"]

EXPOSE 10020 20020 30020
