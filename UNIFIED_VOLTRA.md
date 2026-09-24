# PlayZone + Voltra Unified Runtime

PlayZone and Voltra now run as one application/service.

- PlayZone HTTP/UI: port 8080 in cloud staging
- Embedded Voltra internal API: 127.0.0.1:8086
- MTTL smart-strip listener: TCP 10086
- Manual Voltra page/actions: ROOT only
- Start Session: mapped screen/TV ON
- Pause/Resume: screen power unchanged
- End Session: invoice finalizes, then mapped screen/TV OFF
- The PS4 console remains on a separate power source
- Billing/session validity never depends on Voltra availability

## Real strip connectivity

The current provisioning protocol sends only the server IPv4 address to the strip and the strip connects on TCP port 10086.

Therefore a real Internet host must expose inbound TCP 10086 on a public IPv4 address. Railway can proxy internal TCP 10086, but its public TCP proxy uses a Railway-assigned external port that cannot be fixed to 10086. Railway is suitable for online UI/demo testing, but not for direct connectivity from this strip firmware unless the firmware/provisioning protocol is changed to support a custom server port.

For a real test use a host/VPS with:
- public IPv4
- TCP 10086 allowed inbound
- HTTP/HTTPS for PlayZone
- the same Docker image/runtime
