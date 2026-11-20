#!/usr/bin/env python3
"""Fanju Wi-Fi weather station -> MQTT / Home Assistant.

Developed and tested with the Fanju FJW4. Other models that talk to the same cloud may work, but are untested.

The station talks UDP to a vendor cloud (connect.emaxlife.net, port 10000). This service
takes the place of that cloud, or sits in front of it, and publishes the measurements via
MQTT with Home Assistant autodiscovery. Standard library only.

Modes:
  emulator  Answer the station ourselves, exactly like the cloud does (cloud independent).
            The station's packets must reach us by a router rule (see DOCS.md).
  bridge    Forward everything to the real cloud and relay its answers, only reading the
            measurements on the way. A tiny DNS server points the cloud name at this host.

Packet format (all values little endian):
  aa 3c 57 01 00 | MAC(5) | type(2) | flags(2) | length(2) | payload | checksum(2) | cc 3e
  The checksum is the byte sum of everything before it. Type 53 30 (70 bytes) carries the
  measurements. Temperature = ((raw - 900) / 10 - 32) * 5 / 9 degrees C.
"""
import argparse
import datetime
import json
import os
import socket
import struct
import sys
import threading
import time

CLOUD_IP = "47.52.149.125"
CLOUD_NAME = "connect.emaxlife.net"
PORT = 10000
MAGIC = b"\xaa\x3c\x57\x01\x00"
TAIL = b"\xcc\x3e"


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- decoder

def raw_to_c(raw):
    return ((raw - 900) / 10 - 32) * 5 / 9


def decode(u):
    """70-byte measurement packet -> dict, or None if it is not a valid one."""
    if len(u) != 70 or u[:5] != MAGIC or u[10:12] != b"\x53\x30" or u[68:70] != TAIL:
        return None
    if sum(u[:66]) & 0xFFFF != struct.unpack("<H", u[66:68])[0]:
        return None

    def block(o):
        # three (temperature raw LE16, humidity) triples: current, max, min
        vals = {}
        for i, name in enumerate(("now", "max", "min")):
            raw, hum = struct.unpack("<H", u[o + 3 * i:o + 3 * i + 2])[0], u[o + 3 * i + 2]
            if raw == 0xFFFF:                       # sensor not present
                return None
            vals[name] = (round(raw_to_c(raw), 2), hum)
        return vals

    yy, mo, dd, hh, mi, ss = u[18:24]
    try:
        stamp = datetime.datetime(2000 + yy, mo, dd, hh, mi, ss)
    except ValueError:
        return None
    return {"time": stamp, "mac": "".join("%02x" % b for b in u[5:10]),
            "indoor": block(25), "outdoor": block(34)}


def to_state(r, indoor_offset=0.0):
    """Flat structure published to MQTT."""
    s = {"time": r["time"].isoformat()}
    for name in ("indoor", "outdoor"):
        b = r[name]
        if not b:
            continue
        off = indoor_offset if name == "indoor" else 0.0
        s[name + "_temp"] = round(b["now"][0] + off, 1)
        s[name + "_humidity"] = b["now"][1]
        s[name + "_temp_max"] = round(b["max"][0] + off, 1)
        s[name + "_temp_min"] = round(b["min"][0] + off, 1)
    return s


# --------------------------------------------------------------------------- MQTT (minimal client, QoS 0)

def _s(b):
    b = b.encode() if isinstance(b, str) else b
    return struct.pack(">H", len(b)) + b


def _remaining_length(n):
    out = b""
    while True:
        n, d = divmod(n, 128)
        out += bytes([d | (128 if n else 0)])
        if not n:
            return out


def mqtt_publish(host, port, user, password, messages, client_id="fanju"):
    """messages: [(topic, payload, retain)]. Connects, sends, disconnects."""
    s = socket.create_connection((host, port), timeout=10)
    try:
        flags = 0x02 | (0x80 if user else 0) | (0x40 if user and password else 0)
        vh = _s("MQTT") + bytes([4, flags]) + struct.pack(">H", 30)
        pl = _s(client_id + "-%d" % os.getpid()) + (_s(user) if user else b"") + (_s(password) if user and password else b"")
        s.sendall(b"\x10" + _remaining_length(len(vh + pl)) + vh + pl)
        ack = s.recv(4)
        if len(ack) < 4 or ack[0] != 0x20 or ack[3] != 0:
            raise RuntimeError("MQTT connection refused: %r" % ack)
        for topic, payload, retain in messages:
            body = _s(topic) + (payload.encode() if isinstance(payload, str) else payload)
            s.sendall(bytes([0x30 | (1 if retain else 0)]) + _remaining_length(len(body)) + body)
        s.sendall(b"\xe0\x00")
    finally:
        s.close()


SENSORS = [  # key, name, unit, device_class
    ("indoor_temp", "Indoor Temperature", "°C", "temperature"),
    ("indoor_humidity", "Indoor Humidity", "%", "humidity"),
    ("outdoor_temp", "Outdoor Temperature", "°C", "temperature"),
    ("outdoor_humidity", "Outdoor Humidity", "%", "humidity"),
    ("indoor_temp_max", "Indoor Temperature Max", "°C", "temperature"),
    ("indoor_temp_min", "Indoor Temperature Min", "°C", "temperature"),
    ("outdoor_temp_max", "Outdoor Temperature Max", "°C", "temperature"),
    ("outdoor_temp_min", "Outdoor Temperature Min", "°C", "temperature"),
]

# Sensors become "unavailable" in Home Assistant if the station stays silent this long (seconds).
EXPIRE_AFTER = 900


def mqtt_messages(mac, state, prefix, discovery_prefix):
    dev = {"identifiers": ["fanju_" + mac], "name": "Fanju Weather Station", "manufacturer": "Fanju", "model": "Wi-Fi weather station"}
    state_topic = "%s/%s/state" % (prefix, mac)
    msgs = []
    for key, name, unit, dc in SENSORS:
        cfg = {"name": name, "unique_id": "fanju_%s_%s" % (mac, key), "state_topic": state_topic,
               "value_template": "{{ value_json.%s }}" % key, "unit_of_measurement": unit,
               "device_class": dc, "state_class": "measurement", "expire_after": EXPIRE_AFTER, "device": dev}
        msgs.append(("%s/sensor/fanju_%s/%s/config" % (discovery_prefix, mac, key), json.dumps(cfg, ensure_ascii=False), True))
    msgs.append((state_topic, json.dumps(state), True))
    return msgs


# --------------------------------------------------------------------------- cloud emulation

# Statistics block in the cloud's answer to type 52 30 and forecast block in the answer to
# 52 31 (5 entries of 7 bytes). Copied from captures of the real cloud; the meaning of most
# bytes is unknown, the station only needs them to be well-formed.
STATS_BLOCK = bytes.fromhex("7805523c051e057a26d200b608ffffffff010001000700ff2700")
FORECAST_BLOCK = bytes.fromhex("0b32ff96057805" "0b3cff96056405" "0b50ff50051e05" "0b0aff3c05c404" "0a00ff2805c404")

# After a restart the real cloud answers 13 consecutive heartbeats (57 00) with these push
# messages (MAC and checksum are filled in). Afterwards the station sends data every minute.
PUSH_HEX = [
    "503000010400fc085c038206", "433000010100000f05", "503100010200461e8205", "433100010100001005",
    "5032000104003a07b2041806", "433200010100001105", "5033000102005f149305", "433300010100001205",
    "210100010000bd04", "220100010000be04", "230000010000be04", "240000010000bf04", "250000010000c004"]


def seal(body):
    """Append checksum and end marker."""
    return body + (sum(body) & 0xFFFF).to_bytes(2, "little") + TAIL


def time_bytes(now):
    return bytes([now.year - 2000, now.month, now.day, now.hour, now.minute, now.second])


def make_reply(d, now):
    """Build the cloud's answer to one station packet, or None for unknown packets.

    Handshake after a station restart: 01 01 -> 02 02 -> 52 30 (sets the station clock) ->
    52 31 -> data. Then every minute: heartbeat 00, heartbeat 57, data (about 5 s later).
    """
    if len(d) < 16 or d[:5] != MAGIC or d[-2:] != TAIL:
        return None
    typ = d[10:12]
    if len(d) == 70 and typ == b"\x53\x30":
        return seal(d[:10] + b"\x53\x30\x00\x00\x02\x00OK")
    if len(d) != 20:
        return None
    if typ == b"\x00\x00":
        return seal(d[:12] + b"\x00\x01\x00\x00")
    if typ == b"\x57\x00":
        return seal(d[:12] + b"\x00\x00\x00\x00")
    if typ == b"\x01\x01":
        return seal(d[:12] + b"\x01\x01\x00\x00")
    if typ == b"\x02\x02":
        return seal(d[:12] + b"\x00\x00\x00\x00")
    if typ == b"\x52\x30":
        payload = b"\x81\x0e" + time_bytes(now) + STATS_BLOCK
        return seal(d[:10] + b"\x52\x30\x00\x00" + len(payload).to_bytes(2, "little") + payload)
    if typ == b"\x52\x31":
        payload = b"\x81\x0e" + time_bytes(now) + FORECAST_BLOCK
        return seal(d[:10] + b"\x52\x31\x00\x00" + len(payload).to_bytes(2, "little") + payload)
    return None


def push_packet(d, i):
    """i-th push message for the station whose packet is d."""
    return seal(d[:10] + bytes.fromhex(PUSH_HEX[i])[:-2])


def now_local(a):
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo(a.timezone)).replace(tzinfo=None)
    except Exception:
        return datetime.datetime.now()


# --------------------------------------------------------------------------- DNS redirect (bridge mode)

def _dns_name(q):
    """Return (lower-case query name, offset after the name) of a DNS query."""
    o, out = 12, []
    while o < len(q) and q[o]:
        out.append(q[o + 1:o + 1 + q[o]].decode("ascii", "replace"))
        o += q[o] + 1
    return ".".join(out).lower(), o + 1


def dns_answer(a, sock, q, addr, stat):
    try:
        if len(q) < 17:
            return
        name, end = _dns_name(q)
        qtype = struct.unpack(">H", q[end:end + 2])[0] if end + 2 <= len(q) else 0
        if name == CLOUD_NAME:
            stat["hits"] += 1
            if stat["hits"] <= 3:
                log("DNS: %s -> %s (asked by %s)" % (name, a.host_ip, addr[0]))
            question = q[12:end + 4]
            if qtype == 1:
                resp = q[:2] + b"\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00" + question + \
                    b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x1e\x00\x04" + socket.inet_aton(a.host_ip)
            else:                       # AAAA etc.: empty answer so the station stays on IPv4
                resp = q[:2] + b"\x81\x80\x00\x01\x00\x00\x00\x00\x00\x00" + question
            sock.sendto(resp, addr)
            return
        up = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)    # everything else: ask the real DNS server
        up.settimeout(3)
        up.sendto(q, (a.dns_upstream, 53))
        sock.sendto(up.recv(4096), addr)
        up.close()
    except Exception:
        pass


def dns_server(a):
    """Answer the cloud name with this host's IP, forward every other query upstream."""
    stat = {"hits": 0}
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("0.0.0.0", 53))
    except Exception as e:
        log("DNS server could not start (port 53 unavailable):", e)
        return
    log("DNS redirect active: %s -> %s, all other names go to %s" % (CLOUD_NAME, a.host_ip, a.dns_upstream))
    while True:
        q, addr = sock.recvfrom(1500)
        threading.Thread(target=dns_answer, args=(a, sock, q, addr, stat), daemon=True).start()


# --------------------------------------------------------------------------- servers

def handle(a, data):
    """Decode a station packet and publish it if it is a measurement."""
    r = decode(data)
    if not r:
        return
    state = to_state(r, a.indoor_offset)
    try:
        mqtt_publish(a.mqtt_host, a.mqtt_port, a.mqtt_user, os.environ.get("MQTT_PASSWORD", ""),
                     mqtt_messages(r["mac"], state, "fanju_weather", "homeassistant"))
        log("published:", state["time"], "indoor", state.get("indoor_temp"), "outdoor", state.get("outdoor_temp"))
    except Exception as e:
        log("MQTT error:", e)


def receive(a, sock):
    """Yield (data, addr) of packets from the station; log silence and strangers."""
    sock.settimeout(300)
    total = ignored = 0
    while True:
        try:
            data, addr = sock.recvfrom(2048)
        except socket.timeout:
            log("No packet from the station for 5 minutes (%d so far, %d from other senders). "
                "Check the router setting and restart the station." % (total, ignored))
            continue
        if addr[0] != a.station_ip:
            ignored += 1
            if ignored <= 5:
                log("Ignored packet from %s:%d" % addr)
            continue
        total += 1
        yield data, addr


def serve_emulator(a):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((a.listen, PORT))
    log("Emulator mode: listening on %s:%d for station %s" % (a.listen, PORT, a.station_ip))
    push_i = len(PUSH_HEX)                      # next push message; == length means none pending
    for data, addr in receive(a, sock):
        reply = make_reply(data, now_local(a))
        if len(data) == 20 and data[10:12] == b"\x52\x30":
            push_i = 0                          # station restarted: send the pushes like the cloud
        elif len(data) == 20 and data[10:12] == b"\x57\x00" and push_i < len(PUSH_HEX):
            reply = push_packet(data, push_i)
            push_i += 1
        if reply:
            time.sleep(0.2)                     # the real cloud answers after about 0.2 s
            try:
                sock.sendto(reply, addr)
            except Exception as e:
                log("Reply failed:", e)
        handle(a, data)


def serve_bridge(a):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((a.listen, PORT))
    cloud = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    cloud.connect((CLOUD_IP, PORT))
    log("Bridge mode: listening on %s:%d, forwarding to the cloud %s (station %s)" % (a.listen, PORT, CLOUD_IP, a.station_ip))
    station = {"addr": None}

    def relay_back():                           # cloud -> station
        while True:
            try:
                r = cloud.recv(4096)
            except Exception as e:
                log("Cloud receive failed:", e)
                time.sleep(2)
                continue
            if station["addr"]:
                try:
                    sock.sendto(r, station["addr"])
                except Exception as e:
                    log("Relay to station failed:", e)

    threading.Thread(target=relay_back, daemon=True).start()
    for data, addr in receive(a, sock):
        station["addr"] = addr
        try:
            cloud.send(data)
        except Exception as e:
            log("Forward to cloud failed:", e)
        handle(a, data)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", choices=["emulator", "bridge"], default="emulator")
    p.add_argument("--listen", required=True, help="IP to bind the UDP server to")
    p.add_argument("--station-ip", required=True)
    p.add_argument("--host-ip", default="", help="bridge: IP of this host (answer to the DNS query)")
    p.add_argument("--dns-upstream", default="", help="bridge: normal DNS server for all other names")
    p.add_argument("--indoor-offset", type=float, default=0.0, help="indoor temperature correction in degrees C")
    p.add_argument("--timezone", default="Europe/Berlin", help="time zone of the clock time sent to the station")
    p.add_argument("--mqtt-host", required=True)
    p.add_argument("--mqtt-port", type=int, default=1883)
    p.add_argument("--mqtt-user", default="")
    a = p.parse_args()
    if a.mode == "bridge":
        threading.Thread(target=dns_server, args=(a,), daemon=True).start()
        serve_bridge(a)
    else:
        serve_emulator(a)


if __name__ == "__main__":
    main()
