ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 iproute2 tzdata
COPY fanju_weather.py /fanju_weather.py
COPY run.sh /run.sh
RUN chmod a+x /run.sh
CMD ["/run.sh"]
