# Fanju weather station protocol (reverse engineered)

Everything here was observed with a Fanju FJW4; other models are untested.

The station sends UDP datagrams to `connect.emaxlife.net` (currently `47.52.149.125`), port 10000, and gets an answer
about 0.2 s later. The name is resolved at boot or after a connection loss only. Everything here comes from
network captures of the real cloud and may be incomplete.

## Frame

```
aa 3c 57 01 00 | MAC (5 bytes) | type (2) | flags (2) | length (2, LE) | payload | checksum (2, LE) | cc 3e
```

The checksum is the sum of all bytes before it, modulo 65536. The answer uses the same station MAC.

## Packet types (station -> cloud)

| Type | Length | Meaning | Answer |
|---|---|---|---|
| `01 01` | 20 | login after boot | `01 01 00 00` |
| `02 02` | 20 | login step 2 | `00 00 00 00` |
| `52 30` | 20 | statistics request (hourly) | `81 0e` + time (6 bytes) + 26-byte block |
| `52 31` | 20 | forecast request (hourly) | `81 0e` + time (6 bytes) + 35-byte block (5 x 7 bytes) |
| `00 00` | 20 | heartbeat 1 (every minute) | `00 01 00 00` |
| `57 00` | 20 | heartbeat 2 (about 1 s after heartbeat 1) | `00 00 00 00` |
| `53 30` | 70 | measurements (about 5 s after heartbeat 2) | `02 00` + `OK` |

The time in the `52 30` answer sets the clock of the station. After a station restart the real cloud answers 13
consecutive `57 00` heartbeats with push messages (`50 30`, `43 30`, `50 31`, `43 31`, `50 32`, `43 32`, `50 33`,
`43 33`, `21 01`, `22 01`, `23 00`, `24 00`, `25 00`); the add-on reproduces them (see `PUSH_HEX`).
The contents of the statistics and forecast blocks are copied from real answers; most bytes are not understood. The real cloud sends current values in them (the forecast block holds temperatures); the add-on always sends the same copied block, so the forecast shown on the station is not real in emulator mode.

## Measurement packet (`53 30`, 70 bytes)

| Offset | Content |
|---|---|
| 0-4 | `aa 3c 57 01 00` |
| 5-9 | station MAC |
| 10-11 | `53 30` |
| 18-23 | station time: year-2000, month, day, hour, minute, second |
| 25-33 | indoor: current, max, min, each 3 bytes (raw LE16, humidity %) |
| 34-42 | outdoor sensor 1: same layout |
| 43-51, 52-60 | outdoor sensors 2 and 3 (`ff ff` raw if not present) |
| 66-67 | checksum |
| 68-69 | `cc 3e` |

Temperature in °C: `((raw - 900) / 10 - 32) * 5 / 9` (the raw value is Fahrenheit tenths with an offset of 900).

## Requirements on the network path

The station only accepts answers that return on the same path as its own packets (observed in tests: replies sent directly
from another host than the gateway the request came through appeared to be ignored after the login phase). That is why the
add-on's emulator mode sends its replies via the default gateway.
