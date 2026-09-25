# PlayZone v0.20 - Voltra over Tailscale

## Why this exists

The current Voltra strip provisioning protocol accepts only a server IPv4
address and the strip always connects to TCP port `10086`.

Railway can expose the PlayZone web application, but its public TCP proxy does
not guarantee that the external port is also `10086`. That makes a direct
strip -> Railway connection unsuitable for this firmware.

The Tailscale design keeps Railway as the PlayZone host and adds a small relay
inside the PlayStation LAN:

```text
Voltra strip
    |
    | TCP 10086 to a normal LAN IPv4
    v
LAN relay PC
    |
    | private Tailscale connection
    v
playzone-railway tailnet node :10086
    |
    | userspace-networking inbound proxy
    v
127.0.0.1:10086 (embedded Voltra listener)
```

The strip never needs Tailscale. It only sees the relay PC's normal LAN IPv4.

## 1. Railway / PlayZone side

The PlayZone Docker image installs the Tailscale client. On startup,
`start-staging.sh` starts `tailscaled` in userspace-networking mode when
`TS_AUTHKEY` is present and joins the tailnet.

In Tailscale userspace-networking mode, inbound tailnet connections are proxied
to the same port on `127.0.0.1`. Therefore a connection to the PlayZone
Tailscale node on TCP/10086 reaches the embedded Voltra listener on
`127.0.0.1:10086` without exposing that port publicly.

If Tailscale fails, PlayZone still starts. Billing/session operations therefore
remain independent of Voltra connectivity.

### Railway variables

Set these in Railway:

```text
TS_AUTHKEY=<Tailscale auth key stored as a Railway secret>
TS_HOSTNAME=playzone-railway
TS_STATE_DIR=/data/tailscale
VOLTRA_DEMO=0
```

`VOLTRA_TCP_PORT` defaults to `10086` and normally does not need to be set.

Use a persistent Railway volume for `/data` when possible. Persisting
`TS_STATE_DIR` keeps the Tailscale machine identity and MagicDNS name stable
across redeploys.

Create the auth key from the Tailscale admin console. A tagged key is preferred
for a server workload. Keep the key only in Railway secrets; do not commit it
to Git.

Tailnet access rules should allow only the LAN relay device (or relay tag) to
reach the PlayZone node on TCP/10086.

## 2. LAN relay PC

Use one always-on Windows or Linux machine in the same LAN as the Voltra
strips. It needs:

- Tailscale connected to the same tailnet as Railway.
- Python 3.
- A stable LAN IPv4 address, preferably DHCP-reserved.
- TCP/10086 allowed inbound from the local LAN.

The repository includes:

```text
tools/tailscale_voltra_relay.py
tools/start-voltra-relay-windows.ps1
```

The relay is a raw bidirectional TCP proxy. It does not parse or change the
Voltra protocol.

### Windows

Open PowerShell in the repository and run:

```powershell
.\tools\start-voltra-relay-windows.ps1 `
  -Target playzone-railway.<your-tailnet>.ts.net `
  -ConfigureFirewall
```

Run PowerShell as Administrator the first time if `-ConfigureFirewall` is
used. The firewall rule allows TCP/10086 from `LocalSubnet` only.

If the firewall rule is already managed separately, omit
`-ConfigureFirewall`.

### Linux

With Tailscale already connected:

```bash
python3 tools/tailscale_voltra_relay.py \
  --target playzone-railway.<your-tailnet>.ts.net
```

Allow TCP/10086 only from the local strip LAN.

## 3. Provision the strips

Do **not** provision a strip with the Railway public hostname, Railway TCP proxy
port, Tailscale 100.x address, or MagicDNS name.

Provision each strip with the **LAN IPv4 address of the relay PC**.

Example:

```text
Relay PC LAN IP: 192.168.1.20
Strip server IP: 192.168.1.20
Strip server port: fixed by firmware at 10086
```

Traffic path becomes:

```text
strip -> 192.168.1.20:10086 -> Tailscale -> PlayZone:10086
```

## 4. Validation

On the LAN relay PC:

```powershell
tailscale ping playzone-railway
Test-NetConnection playzone-railway.<your-tailnet>.ts.net -Port 10086
```

Then start the relay. It should log a line similar to:

```text
Listening on 0.0.0.0:10086 -> playzone-railway.<tailnet>.ts.net:10086
```

When a strip connects, the relay logs a connection and the strip should appear
in the Voltra management flow in PlayZone.

On Railway, successful startup prints:

```text
Tailscale connected. Userspace networking will forward inbound tailnet TCP/10086 to localhost:10086.
Private Voltra endpoint: 100.x.y.z:10086
```

If Tailscale does not authenticate, PlayZone continues running but the private
Voltra path is unavailable. Check the Railway `TS_AUTHKEY`, Tailscale device
authorization, persisted state, and tailnet access rules.

## 5. Production notes

- Give the relay PC a DHCP reservation/static LAN address.
- Run the relay automatically at Windows startup or as a Linux systemd service
  after validation.
- Keep `TS_AUTHKEY` secret.
- Restrict tailnet access so only the relay can reach PlayZone TCP/10086.
- Restrict the relay's Windows/Linux firewall so only the local strip LAN can
  reach TCP/10086.
- Keep the PS4 console on its separate power source as before; only the mapped
  display/TV power is controlled by Voltra.
