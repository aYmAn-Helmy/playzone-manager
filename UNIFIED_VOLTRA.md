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

The current provisioning protocol sends only a server IPv4 address to the strip
and the strip connects on TCP port 10086.

Railway's public TCP proxy cannot guarantee an external port of 10086, so the
strip should not connect directly to Railway.

The v0.20 connectivity path uses Tailscale plus a small LAN relay:

```text
Voltra strip -> LAN relay IPv4:10086 -> Tailscale -> Railway PlayZone:10086
```

The relay PC is on the same LAN as the strips. The strips are provisioned with
the relay PC's ordinary LAN IPv4 address, while the relay forwards raw TCP over
Tailscale to the private PlayZone endpoint.

On Railway, `start-staging.sh` starts Tailscale in userspace mode when
`TS_AUTHKEY` is configured and exposes the embedded listener privately with a
Tailscale TCP forwarder. If Tailscale is unavailable, PlayZone still starts and
billing/session operations continue normally.

See `TAILSCALE_VOLTRA.md` for Railway variables, relay setup, Windows/Linux
commands, strip provisioning, and validation steps.
