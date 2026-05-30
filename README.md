# HA Iotics Smart Home Add-on

A Home Assistant add-on to connect your **Iotics smart home devices** with fully automatic discovery. Just enter your Iotics login credentials and it discovers all your switches, lights, fans, sockets, and AC units — with their real names — in real-time.

## Features

- **Zero configuration** — enter your Iotics email and password, everything else is automatic
- **Auto-discovers** all devices, buttons, and labels from the Iotics cloud — no hardcoded room or button mappings
- **Real-time state sync** polls the Iotics cloud every 5 seconds so HA always shows the correct device state
- **Bidirectional control** — toggle a switch in HA and the physical device responds; press a wall switch and HA updates instantly
- **Fan speed control** — speed sliders with 1-4 fan speed buttons per fan
- **Auto-generated dashboard** — a dedicated Lovelace dashboard is created with all your rooms and devices
- **Self-cleaning** — devices or buttons removed from the Iotics app are automatically cleaned up from HA
- **State preservation** — never forces devices off on startup; respects current physical states
- **Standalone** — works independently on any HA installation (HAOS, Docker, or supervised)

## Prerequisites

- Home Assistant (HAOS, Docker, or supervised installation)
- An active Iotics account with smart home devices registered
- Your Iotics login credentials (email + password)
- Iotics devices must be on the same local network as your HA server (for HTTP command control)

## Installation

### 1. Add the repository to HA

1. Go to **Settings → Add-ons → Add-on Store**
2. Click the **⋮ menu** (top right) → **Repositories**
3. Add this repository URL:
   ```
   https://github.com/keithcardozo10-dev/ha-iotics-addon
   ```
4. Click **Add**

### 2. Install the add-on

1. The **Iotics Smart Home Bridge** add-on appears in the store
2. Click it, then click **Install**
3. Wait for the installation to complete

### 3. Configure

1. Go to the **Configuration** tab
2. Enter your Iotics credentials:
   - **iotics_email**: Your Iotics account email (e.g., `you@example.com`)
   - **iotics_password**: Your Iotics account password
3. Click **Save**

### 4. Start

1. Go to the **Info** tab
2. Toggle **Start on boot** to ON (recommended)
3. Click **Start**
4. Watch the **Log** tab for progress

```
[CLOUD] Starting cloud poll loop (5s interval, no hardcoded mappings)
[CLOUD] New device: Kitchen (48551912a0e4)
[CLOUD] New device: Hall 1.1 (58bf25db1332)
...
[LOVELACE] Dashboard pushed: 7 rooms
[HEARTBEAT] 7 rooms, 8 devices, 42 buttons
```

### 5. Access your dashboard

A new **Iotics Smart Home** view is added to your Lovelace dashboard automatically. You can also access it directly at:

```
http://your-ha-instance:8123/iotics
```

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                     Iotics Cloud API                            │
│          https://api.iotics.io (login + getdevices)             │
└───────────────────┬─────────────────────────────────────────┬───┘
                    │ polls every 5s                           │
                    ▼                                          │
┌──────────────────────────────────────┐                       │
│        Iotics Bridge Add-on          │                       │
│  ┌────────────────────────────────┐  │                       │
│  │ Cloud Poll Loop (READ-ONLY)    │  │    HTTP commands      │
│  │ - Login to Iotics API          │──┼───────────────────────┤
│  │ - Get all devices + states     │  │                       │
│  │ - Sync to HA entities          │  │                       │
│  │ - Create/update input_booleans │  │                       │
│  │ - Create/update input_numbers  │  │                       │
│  │ - Clean up orphans             │  │                       │
│  └────────────────────────────────┘  │                       │
│  ┌────────────────────────────────┐  │                       │
│  │ WS Command Listener            │──┼──────────────────►    │
│  │ - Listens for HA state changes │  │  Iotics Physical      │
│  │ - Detects user toggles         │  │  Devices              │
│  │ - Fires HTTP commands          │  │  (on local network)   │
│  │ - Includes fan speed control   │  │                       │
│  └────────────────────────────────┘  │                       │
│  ┌────────────────────────────────┐  │                       │
│  │ Dashboard Generator            │  │                       │
│  │ - Creates Lovelace view        │  │                       │
│  │ - Organizes by room            │  │                       │
│  │ - Fan speed buttons per room   │  │                       │
│  └────────────────────────────────┘  │                       │
└───────────────────┬──────────────────┘                       │
                    │                                          │
                    ▼                                          │
┌──────────────────────────────────────┐                       │
│          Home Assistant              │                       │
│  input_boolean.iotics_kitchen_fan    │                       │
│  input_number.iotics_kitchen_speed   │                       │
│  ... (all discovered entities)       │                       │
└──────────────────────────────────────┘                       │
```

## Entity Naming

Entities are named automatically based on your Iotics device names and labels:

- **Switches**: `input_boolean.iotics_{room}_{label}`
- **Fan speeds**: `input_number.iotics_{room}_{label}`

Example: If your Iotics app shows "Kitchen" with a button labeled "Right Light", the entity becomes `input_boolean.iotics_kitchen_right_light`.

## Dashboard

The add-on creates a dedicated **Iotics Smart Home** Lovelace view with:

- Rooms organized alphabetically with headings
- Each device's switches shown as toggle cards (4 per row)
- Fan speeds shown as 4 speed buttons (1-2-3-4) with fan icon
- Speed buttons highlight when the active speed matches

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| "Login failed" in log | Wrong email/password | Check credentials in add-on config, restart |
| No devices appear | Iotics account has no registered devices | Verify in the Iotics mobile app |
| Toggle doesn't turn device on/off | Device IP not reachable | Ensure Iotics devices are on the same network |
| Entities show old state | Cloud sync in progress | Wait up to 5 seconds for the next poll |
| Dashboard not showing | First sync may take 30s | Check logs for "Dashboard pushed" |
| "Device fan speed doesn't change" | Some fan models need MQTT | Bridge uses HTTP fallback; add-on supports MQTT via config extension |
| HA restart shows all off | Entities created but init state unknown | Cloud poll syncs real state within 5 seconds of startup |

## Manual Installation (without HA add-on store)

If you can't use the add-on store, you can run the bridge as a standalone Python script:

```bash
# Install dependencies
pip3 install paho-mqtt websocket-client requests aiohttp

# Run the bridge
export IOTICS_EMAIL="you@example.com"
export IOTICS_PASSWORD="your_password"
export HASS_TOKEN="your_ha_long_lived_token"
export HASS_URL="http://homeassistant.local:8123"
python3 bridge.py
```

Get your HA long-lived token from: **Settings → Security → Long-Lived Access Tokens**

## Development

### Repository structure

```
ha-iotics-addon/
├── README.md               # This file
├── repository.json         # HA add-on store listing
└── iotics-addon/
    ├── config.yaml         # Add-on configuration
    ├── Dockerfile          # Container build
    ├── run.sh              # Entrypoint script
    ├── install.sh          # Post-install deps
    └── bridge.py           # The bridge itself
```

### Building locally

```bash
# Clone
git clone https://github.com/keithcardozo10-dev/ha-iotics-addon
cd ha-iotics-addon

# Build (requires Docker with buildx)
docker buildx build \
  --platform linux/amd64,linux/arm64,linux/arm/v7 \
  -t ghcr.io/keithcardozo10-dev/ha-iotics-addon \
  -f iotics-addon/Dockerfile \
  iotics-addon/
```

## License

MIT
