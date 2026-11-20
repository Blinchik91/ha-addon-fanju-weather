# Fanju Weather Station – local Home Assistant add-on

Read **Fanju Wi-Fi weather stations** locally and get its values into Home Assistant via MQTT,
with or without the vendor cloud.

The station only talks to a vendor cloud server (UDP, `connect.emaxlife.net`, port 10000) and offers no local
interface. This add-on takes the place of that server, or sits in front of it, so that the measurements
arrive in Home Assistant about once a minute.

> **Unofficial project.** Not affiliated with or endorsed by Fanju, EMAX or any brand sold under them. The
> protocol was reverse-engineered from network captures. Use at your own risk; read [Risks](#risks-and-side-effects).

## Features

* Indoor and outdoor temperature and humidity, daily min/max, one reading per minute
* MQTT autodiscovery: a device with eight sensors appears automatically
* **Emulator mode:** works without any internet access or vendor cloud
* **Bridge mode:** forwards to the real cloud, so the vendor app keeps working
* Other routers work as long as they can do what the setup below asks for.

## Supported devices

| Device | Status |
|---|---|
| Fanju FJW4 (Wi-Fi weather station) | **works**, tested with Home Assistant OS on a Raspberry Pi 4 behind a FRITZ!Box |
| Other Fanju stations, or the same hardware sold under other brand names | **untested**. They may use the same cloud and protocol, but this is not known |

If you try another model, please open an issue with the result (and, if it does not work, a capture of its
traffic to `connect.emaxlife.net`).

## How it works

```
Station --UDP--> connect.emaxlife.net (47.52.149.125:10000)

emulator:  Station --> router --(static route)--> Home Assistant add-on answers like the cloud
bridge:    Station --> (DNS says: cloud = Home Assistant) --> add-on --> real cloud
                                                              \--> MQTT --> Home Assistant
```

The station resolves the cloud name only at boot or after a connection loss, then keeps sending to that
address. So the traffic has to be steered **to Home Assistant** by your network. That is the one thing
you must set up on your router.

## Choose a mode

| | `emulator` | `bridge` |
|---|---|---|
| Vendor cloud / app | no new data | keep working |
| Weather forecast on the station | **not available** (fixed placeholder data) | real forecast from the cloud |
| Internet needed | no | yes |
| Router change | one static route (`/32`) | DNS server for your network |
| Other devices affected | practically none | yes, they use Home Assistant for DNS |
| Failure when add-on is down | no data in HA | DNS outage in the whole network |

If you do not need the app, use **emulator**. It is the safer option.

## Installation

Requires Home Assistant OS or a Supervised installation (add-ons are not available in Container / Core installs)
and an MQTT broker, for example the **Mosquitto broker** add-on with the MQTT integration set up.

### 1. Add the repository

[![Open your Home Assistant instance and show the add add-on repository dialog with this repository pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FBlinchik91%2Fha-addon-fanju-weather)

Click the button, or add it manually:
*Settings → Add-ons → Add-on Store → ⋮ (top right) → Repositories*, paste
`https://github.com/Blinchik91/ha-addon-fanju-weather` and click *Add*.

### 2. Install the add-on

Reload the Add-on Store page, scroll to **Fanju Weather Station**, open **Fanju Weather Station (Local Server)** and click *Install*.

### 3. Configure

Open the *Configuration* tab:

* `mode`: `emulator` (no cloud) or `bridge` (keep the app working), see [Choose a mode](#choose-a-mode)
* `station_ip`: IP address of the station (give it a fixed address in your router first)
* `timezone`: for example `Europe/Berlin`

### 4. Set up your router, then start

**Do not start the add-on before you have done the [router setup](#router-setup).** Then click *Start* and
power-cycle the station (unplug it for a few seconds). Check the *Log* tab: after a minute you should see
`published: …` lines, and the device **Fanju Weather Station** appears under *Settings → Devices & services → MQTT*.

Optional: enable *Start on boot* and *Watchdog*.

### Manual installation (without GitHub)

Copy the `fanju_weather` folder into the `addons` share of Home Assistant (Samba add-on, or `/addons` via SSH),
then reload the Add-on Store. The add-on appears under *Local add-ons*.

### Updating and uninstalling

Updates appear in the Add-on Store when a new version is released. Before uninstalling, revert your router
setting (static route or DNS server) so the station is not left pointing at a host that no longer answers.
Delete the device under *Settings → Devices & services → MQTT* if you do not want the sensors any more.

## Router setup

Any router that can do the following works; the FRITZ!Box is only an example.

### Emulator mode: static route

Add a static IPv4 route: destination `47.52.149.125`, netmask `255.255.255.255` (`/32`), next hop = IP of Home Assistant.

* FRITZ!Box: *Home Network → Network → Network Settings → IPv4 Routes → Add*
* OpenWrt: *Network → Routing → Static IPv4 Routes*
* Other routers: look for "static route" / "custom route"

Only traffic to that single address is affected.

### Bridge mode: DNS server

The router has to hand out the IP of Home Assistant as DNS server to the network (or at least to the station).
The add-on answers `connect.emaxlife.net` with its own IP and forwards all other names to your router.

* FRITZ!Box: *Home Network → Network → Network Settings → IPv4 Addresses → Local DNS server*
* Others: DHCP option 6 / "DNS server" setting of the LAN

If your router can give **only one device** a different DNS server, use that for the station and leave
everybody else alone. This avoids the risks below.

After any change, restart the add-on and power-cycle the station: it only looks up the name at boot.

## Configuration

| Option | Description |
|---|---|
| `mode` | `emulator` or `bridge` |
| `station_ip` | IP address of the station |
| `timezone` | IANA time zone, e.g. `Europe/Berlin`. In emulator mode the station's clock is set from it |
| `indoor_offset` | Correction in °C for the indoor temperature (default `0`) |

## Entities

Device *Fanju Weather Station*:

`Indoor/Outdoor Temperature`, `Indoor/Outdoor Humidity`, `Indoor/Outdoor Temperature Max`, `Indoor/Outdoor Temperature Min`.

The values are retained in MQTT. Sensors become `unavailable` after 15 minutes without a packet.

## Limitations of the emulator mode

In emulator mode the vendor cloud is replaced, so everything the cloud normally provides to the station and the app is missing:

* **No weather forecast on the station.** The forecast data on the station's display and the hourly statistics come
  from the cloud. The add-on answers the station's requests with fixed placeholder data that was copied from a real
  answer, so the forecast shown on the station is **not real and not updated**. Ignore it, or use bridge mode
  if you want it.
* **No app, no cloud history and no cloud services** (account, remote access, push messages of the app).
* The measurements are unaffected: indoor/outdoor temperature and humidity are measured and sent by the station
  itself and arrive in Home Assistant as usual. The clock of the station is set by the add-on from your time zone.
* Only what we learned from captures is emulated. Functions of the cloud that we have not seen cannot be answered.

Use **bridge** mode if you need any of these.

## Risks and side effects

Please read this before you install the add-on.

**Network**

* **Bridge mode makes Home Assistant your DNS server.** If the add-on or Home Assistant is down, all devices that use
  it lose name resolution until you revert the router setting. The built-in DNS server is minimal: UDP only, no
  caching, no TCP fallback. Prefer applying the DNS setting only to the station.
* Port 53 is used in bridge mode, so it cannot run next to another DNS server on the same host
  (AdGuard Home, Pi-hole, ...).
* **Emulator mode removes the station from the vendor cloud.** The app and any cloud service no longer
  receive data. If the vendor ever changes the server address, the static route no longer matches and the
  data stops.
* In bridge mode your data still goes to the vendor cloud, exactly as without the add-on.

**Host changes** (the add-on runs with host networking and `NET_ADMIN`)

* In emulator mode it adds `47.52.149.125/32` to the loopback interface, a host route to the station via your
  default gateway, and disables acceptance of ICMP redirects (`net.ipv4.conf.all.accept_redirects`,
  and the active interface). Address and route are removed when the add-on stops; the sysctl value stays until
  the next host reboot.
* It reports its measurements by publishing to your MQTT broker with the credentials Home Assistant provides.

**Security**

* The station protocol is unauthenticated UDP. The add-on only accepts packets from `station_ip`, but this
  is not secure against spoofing inside your LAN. Do not expose ports 10000 or 53 to the internet.
* In emulator mode the add-on sets the station's clock; nothing else is sent to the station.

**Other**

* The add-on is developed for the FJW4. Other models may behave differently. A firmware update could change the protocol. Unknown packet types are not answered.
* Provided "as is", without warranty. You are responsible for the changes you make to your network.

## Troubleshooting

* *No packet from the station for 5 minutes*: check the route or DNS setting, power-cycle the station.
* *Packets arrive but no data after the first minute (emulator)*: the station ignores answers that do not take
  the same path as its own packets. The add-on routes its replies back through your default gateway; this requires
  that the station reaches the add-on **through the router**, as with the static route. A DNS redirect with
  `emulator` is not supported.
* *Outdoor humidity differs from the app*: the values in the packets are shown as received.
* *No sensors in Home Assistant*: check the MQTT integration and the MQTT discovery prefix (`homeassistant`).

## Why this approach

* **The station is never modified.** Nothing is written to the device or its Wi-Fi module: no settings are changed,
  no firmware is touched. The station keeps its factory configuration and simply talks to the address it always
  talked to. If you remove the add-on and the router setting, everything is back to the original state.
* **Only the network path is changed, on your router.** The add-on does not depend on special features of the
  station's Wi-Fi module (such as a configuration port), so it does not matter which module is built in. It only
  needs the station's own upload traffic, which every station that uses the vendor cloud sends.
* **No account and no cloud access needed.** In emulator mode the add-on answers the station itself, so it works
  without internet and without your vendor credentials. In bridge mode the original cloud conversation is passed
  through unchanged.
* **Works without polling.** The values arrive as the station sends them, about once a minute, instead of being
  fetched from a server at long intervals.
* **Everything is reversible.** Changes on the Home Assistant host are removed when the add-on stops, and the
  router setting can be reverted at any time.

Please also read [Risks and side effects](#risks-and-side-effects): the router setup has consequences you should know about.

## Protocol

See [docs/PROTOCOL.md](docs/PROTOCOL.md).

## Contributing

Issues and pull requests are welcome, especially: reports for other station models (working or not), router setup guides and
captures of unknown packet types.

## License

[MIT](LICENSE)
