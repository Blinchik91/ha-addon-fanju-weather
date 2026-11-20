# Fanju Weather Station (Local Server)

Reads Fanju Wi-Fi weather stations locally and publishes the values to Home Assistant via MQTT
(autodiscovery). Requires an MQTT broker, for example the Mosquitto add-on.

**Read the network setup below before you start the add-on.** The add-on does nothing until your router sends
the station's traffic to Home Assistant.

## Supported devices

Developed and **successfully tested with the Fanju FJW4**. Other weather stations of the same brand (or
sold under other names) may use the same cloud and protocol and could work, but **have not been tested**.
Reports are welcome.

## Entities

Device "Fanju Weather Station": indoor/outdoor temperature, indoor/outdoor humidity and the
daily min/max temperatures. The station reports about once a minute. The sensors become `unavailable` after
15 minutes without a packet.

## Choose a mode (option `mode`)

| | `emulator` | `bridge` |
|---|---|---|
| Vendor cloud and app | no new data (cloud is replaced) | keep working |
| Forecast on the station | not real (placeholder data) | real forecast |
| Needs internet | no | yes |
| Router change | static route for one IP | DNS server for the whole network |
| Affects other devices | no (one /32 route) | yes (they use Home Assistant for DNS) |

### emulator (cloud independent)

The add-on answers the station like the vendor cloud, so the station works completely locally. Limitations:
the **weather forecast on the station is not real** (the add-on sends fixed placeholder data), and the app, cloud history
and other cloud services are not available. The measurements are not affected. Use `bridge` if you need these. Setup:

1. Router: add a static IPv4 route, destination `47.52.149.125`, netmask `255.255.255.255`, gateway = IP of Home Assistant.
   (FRITZ!Box: Home Network → Network → Network Settings → IPv4 Routes.)
2. Start the add-on, then power-cycle the station so that it reconnects.

### bridge (keep the app working)

The add-on forwards the station's packets to the real cloud and relays the answers unchanged; it only reads
the measurements. A small DNS server inside the add-on answers `connect.emaxlife.net` with the IP of Home
Assistant and forwards every other name to your router.

1. Router: make Home Assistant the DNS server that is handed out to your devices.
   (FRITZ!Box: Home Network → Network → Network Settings → IPv4 Addresses → "Local DNS server".)
   Remove the emulator route if you had one.
2. Start the add-on, then power-cycle the station.

**Risk:** every device that takes its DNS from the router now depends on this add-on. If the add-on or Home
Assistant is down, name resolution fails for those devices until the router setting is reverted. The built-in
DNS server is minimal (UDP only, no caching, no TCP fallback). It also needs port 53, so it conflicts with other
DNS add-ons such as AdGuard Home or Pi-hole.

### Switching modes

Change the router setting (route <-> DNS server), change `mode`, restart the add-on, power-cycle the station.

## Options

| Option | Description |
|---|---|
| `mode` | `emulator` or `bridge` |
| `station_ip` | IP address of the station (use a DHCP reservation) |
| `timezone` | IANA time zone, e.g. `Europe/Berlin`. In emulator mode the station clock is set from it |
| `temperature_unit` | `celsius` (default) or `fahrenheit`: unit of the temperature sensors. The station measures in Fahrenheit internally. Changing it later changes the unit of the sensors; Home Assistant then reports a unit change for the long-term statistics of these sensors |
| `indoor_offset` | Correction in °C added to the indoor temperature, normally `0` |

## What the add-on changes on the host

The add-on needs host networking and the `NET_ADMIN` capability. In emulator mode it adds `47.52.149.125/32` to the
loopback interface, adds a host route for the station via your default gateway (so replies take the same
path as the station's packets, which the station requires) and turns off ICMP redirect acceptance
(`net.ipv4.conf.all.accept_redirects` and on the active interface). The address and route are removed
when the add-on stops; the sysctl setting is not restored until the host reboots. In bridge mode it only listens on UDP ports 10000 and 53.

## Troubleshooting

* Log says `No packet from the station for 5 minutes`: check the router route / DNS setting and power-cycle the station.
* Station shows no data in HA but the log shows packets: check the MQTT add-on and the MQTT integration.
* Check the log of the add-on first: it shows which mode is active and which addresses were detected.

More information, the protocol description and the security notes are in the repository README.
