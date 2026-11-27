# Changelog

## 1.0.2

* Fix: the add-on could fail to start after a host reboot (exit code 141). The network detection used a pipe that
  can be killed with SIGPIPE; it now parses the output in bash. The add-on also waits up to a minute for the network
  to be ready before giving up.

## 1.0.1

* New option `temperature_unit`: publish temperatures in Celsius (default) or Fahrenheit.
* The log is quiet by default (start-up, first measurement, problems). New option `debug` logs every measurement.
* Repeated "no packet" and MQTT error messages are throttled; recovery is logged once.
* Documentation: limitations of the emulator mode (no real forecast on the station), "Why this approach" section.

## 1.0.0

* First release.
* Emulator mode (cloud independent) and bridge mode (forwards to the real cloud).
* MQTT autodiscovery for indoor/outdoor temperature, humidity and daily min/max.
* Tested with the Fanju FJW4.
