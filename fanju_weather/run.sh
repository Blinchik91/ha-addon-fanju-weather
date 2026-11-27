#!/usr/bin/with-contenv bashio
# Add-on start script.
#
# The station resolves connect.emaxlife.net and sends UDP packets to the cloud (47.52.149.125:10000).
# How those packets reach this add-on depends on the mode:
#
#  emulator  The router has a static route 47.52.149.125/32 -> this host. The add-on adds the cloud
#            address to the loopback interface and answers like the cloud. Replies to the station are
#            routed back through the router, because the station ignores replies that arrive on a
#            different path than its own packets.
#  bridge    A small DNS server inside the add-on points the cloud name at this host (the router must
#            hand out this host as DNS server). Packets are forwarded to the real cloud.

CLOUD_IP="47.52.149.125"
PORT=10000
MODE="$(bashio::config 'mode')"
STATION_IP="$(bashio::config 'station_ip')"
if [ -z "${STATION_IP}" ]; then
    bashio::log.fatal "Option station_ip is empty. Enter the IP address of the weather station and restart."
    exit 1
fi
export MQTT_PASSWORD="$(bashio::services mqtt password)"
export PYTHONUNBUFFERED=1

# Detect this host's address, the default gateway and the network interface. Right after a boot the
# network may not be ready yet, so retry for up to a minute. Note: the output is captured in a variable
# and parsed with bash only; a pipe such as "ip ... | head -n1" can kill "ip" with SIGPIPE (exit code 141)
# because this script runs with "set -e -o pipefail".
HOST_IP=""
GATEWAY=""
IFACE=""
for _ in $(seq 1 30); do
    ROUTE_OUT="$(ip -o route get 1.1.1.1 2>/dev/null || true)"
    ROUTE="${ROUTE_OUT%%$'\n'*}"
    if [[ "${ROUTE}" =~ \ src\ ([0-9.]+) ]]; then HOST_IP="${BASH_REMATCH[1]}"; fi
    if [[ "${ROUTE}" =~ \ via\ ([0-9.]+) ]]; then GATEWAY="${BASH_REMATCH[1]}"; fi
    if [[ "${ROUTE}" =~ \ dev\ ([^\ ]+) ]]; then IFACE="${BASH_REMATCH[1]}"; fi
    if [ -n "${HOST_IP}" ] && [ -n "${GATEWAY}" ] && [ -n "${IFACE}" ]; then
        break
    fi
    HOST_IP=""
    GATEWAY=""
    IFACE=""
    sleep 2
done
if [ -z "${HOST_IP}" ]; then
    bashio::log.fatal "Could not detect the network setup (host address / gateway). Is the network up?"
    exit 1
fi

STATION_ROUTE=0
LO_ALIAS=0
PID=""

cleanup() {
    [ -n "${PID}" ] && kill "${PID}" 2>/dev/null
    [ "${STATION_ROUTE}" = "1" ] && ip route del "${STATION_IP}/32" 2>/dev/null
    [ "${LO_ALIAS}" = "1" ] && ip addr del "${CLOUD_IP}/32" dev lo 2>/dev/null
}
trap cleanup TERM INT

if [ "${MODE}" = "bridge" ]; then
    LISTEN="0.0.0.0"
    MODE_ARGS=(--host-ip "${HOST_IP}" --dns-upstream "${GATEWAY}")
    bashio::log.info "Bridge mode: make the router hand out ${HOST_IP} as DNS server, then restart the station."
else
    LISTEN="${CLOUD_IP}"
    MODE_ARGS=()
    LO_INFO="$(ip addr show dev lo)"
    if [[ "${LO_INFO}" != *"inet ${CLOUD_IP}/32"* ]]; then
        if ip addr add "${CLOUD_IP}/32" dev lo; then
            LO_ALIAS=1
        else
            bashio::log.fatal "Could not add ${CLOUD_IP} to the loopback interface (NET_ADMIN / host network required)."
            exit 1
        fi
    fi
    # Send replies to the station via the router (symmetric path) and ignore ICMP redirects.
    sysctl -w net.ipv4.conf.all.accept_redirects=0 >/dev/null 2>&1 || true
    sysctl -w "net.ipv4.conf.${IFACE}.accept_redirects=0" >/dev/null 2>&1 || true
    if ip route replace "${STATION_IP}/32" via "${GATEWAY}" dev "${IFACE}"; then
        STATION_ROUTE=1
    else
        bashio::log.warning "Could not set the reply route for ${STATION_IP}; the station may not send measurements."
    fi
    bashio::log.info "Emulator mode: the router needs a route ${CLOUD_IP}/255.255.255.255 -> ${HOST_IP}."
fi

DEBUG_ARGS=()
if bashio::config.true 'debug'; then
    DEBUG_ARGS=(--debug)
fi

python3 /fanju_weather.py \
    --mode "${MODE}" \
    --listen "${LISTEN}" \
    --station-ip "${STATION_IP}" \
    --indoor-offset "$(bashio::config 'indoor_offset')" \
    --temperature-unit "$(bashio::config 'temperature_unit')" \
    "${DEBUG_ARGS[@]}" \
    --timezone "$(bashio::config 'timezone')" \
    --mqtt-host "$(bashio::services mqtt host)" \
    --mqtt-port "$(bashio::services mqtt port)" \
    --mqtt-user "$(bashio::services mqtt username)" \
    "${MODE_ARGS[@]}" &
PID=$!
wait "${PID}"
cleanup
