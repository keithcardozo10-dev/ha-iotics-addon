#!/usr/bin/env python3
"""
Iotics Smart Home Bridge – HA Add-on Edition
=============================================
Connect your Iotics smart home devices to Home Assistant with zero config.
Just provide your Iotics login credentials and the add-on auto-discovers:

  - All devices (kitchen, hall, bedroom, etc.) with their actual names
  - All buttons/controls per device (lights, fans, sockets, AC, etc.)
  - All fan speed controls
  - Real-time state updates via Iotics cloud API polling

Features:
  - Fully dynamic – no hardcoded device/room/button mappings
  - Auto-creates input_boolean entities for on/off switches
  - Auto-creates input_number entities for fan speeds (slider mode)
  - Real-time sync via Iotics cloud API (5s polling)
  - Command execution: toggle a switch in HA → device responds physically
  - Dashboard auto-generated with all discovered rooms and devices
  - State persistence: never auto-toggles on startup
  - Orphan cleanup: removes entities for devices/buttons no longer in the cloud

Usage (add-on mode):
  Set iotics_email and iotics_password in the add-on config.
  The add-on handles everything else.

Usage (standalone CLI):
  export IOTICS_EMAIL="your@email.com"
  export IOTICS_PASSWORD="your_password"
  export IOTICS_APPID="696f74696373617070"
  export HASS_TOKEN="your_ha_token"
  export HASS_URL="http://homeassistant.local:8123"
  python3 bridge.py
"""

import hashlib, hmac, json, logging, os, re, ssl, subprocess, sys, threading, time
import urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "info").upper()
LOG_PATH = os.environ.get("LOG_FILE", "/tmp/iotics_bridge.log")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("iotics-bridge")

# HA connection (try env vars, then supervisor token)
HASS_TOKEN = os.environ.get("HASS_TOKEN", os.environ.get("SUPERVISOR_TOKEN", ""))
HASS_URL = os.environ.get("HASS_URL", "http://supervisor/core")

# Iotics cloud credentials
IOTICS_EMAIL = os.environ.get("IOTICS_EMAIL", "")
IOTICS_PASSWORD = os.environ.get("IOTICS_PASSWORD", "")
IOTICS_APPID = os.environ.get("IOTICS_APPID", "696f74696373617070")

# Parse CLI args (overrides env vars)
_known_flags = {
    "--ha-token": "HASS_TOKEN", "--ha-url": "HASS_URL",
    "--iotics-email": "IOTICS_EMAIL", "--iotics-password": "IOTICS_PASSWORD",
    "--iotics-appid": "IOTICS_APPID",
    "--log-level": "LOG_LEVEL", "--log-file": "LOG_FILE",
}
_skip_next = False
for _i, _a in enumerate(sys.argv[1:]):
    if _skip_next:
        _skip_next = False
        continue
    if _a in _known_flags:
        _env = _known_flags[_a]
        _val = sys.argv[_i + 2] if _i + 2 < len(sys.argv) else ""
        if _env == "LOG_FILE":
            LOG_PATH = _val
        elif _env == "LOG_LEVEL":
            LOG_LEVEL = _val.upper()
            logging.getLogger().setLevel(LOG_LEVEL)
        else:
            os.environ[_env] = _val
            if _env == "HASS_TOKEN":
                HASS_TOKEN = _val
            elif _env == "HASS_URL":
                HASS_URL = _val
            elif _env == "IOTICS_EMAIL":
                IOTICS_EMAIL = _val
            elif _env == "IOTICS_PASSWORD":
                IOTICS_PASSWORD = _val
            elif _env == "IOTICS_APPID":
                IOTICS_APPID = _val
        _skip_next = True

# ── /data/options.json fallback (HA addon mode) ────────────────────────────
OPTIONS_PATH = Path("/data/options.json")
if OPTIONS_PATH.exists():
    try:
        opts = json.loads(OPTIONS_PATH.read_text())
        IOTICS_EMAIL = opts.get("iotics_email", IOTICS_EMAIL) if not IOTICS_EMAIL else IOTICS_EMAIL
        IOTICS_PASSWORD = opts.get("iotics_password", IOTICS_PASSWORD) if not IOTICS_PASSWORD else IOTICS_PASSWORD
        IOTICS_APPID = opts.get("iotics_appid", IOTICS_APPID)
    except Exception as e:
        log.warning("Failed reading /data/options.json: %s", e)

log.info("Config: email=%s appid=%s", IOTICS_EMAIL[:4] + "..." if IOTICS_EMAIL else "(empty)", IOTICS_APPID)

# ── State ──────────────────────────────────────────────────────────────────
DEVICES = {}         # token (lowercase mac) -> {room_key, buttons: {btn: {label, type, is_fan}}}
ENTITY_CACHE = {}    # entity_id -> JSON state string (for change detection)
LAST_CMD = {}        # entity_id -> timestamp (anti-loop cooldown)
CMD_COOLDOWN = 2     # seconds between same-entity commands
IP_CACHE = {}        # token -> ip address

# ── HA REST helpers ────────────────────────────────────────────────────────
def ha_get(path):
    try:
        req = urllib.request.Request(
            f"{HASS_URL}/api/{path}",
            headers={"Authorization": f"Bearer {HASS_TOKEN}"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        log.debug("HA GET %s: %s", path, e)
        return None

def ha_post(path, data):
    try:
        req = urllib.request.Request(
            f"{HASS_URL}/api/{path}",
            data=json.dumps(data).encode(),
            headers={"Authorization": f"Bearer {HASS_TOKEN}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        log.debug("HA POST %s: %s", path, e)
        return None

# ── Entity helpers ─────────────────────────────────────────────────────────
def sanitize_label(label):
    """Convert a label into a safe entity-name slug."""
    s = label.strip().lower()
    s = re.sub(r'[^a-z0-9]+', '_', s)
    s = s.strip('_')
    return s if s else "switch"

def build_eid(room_key, label, is_fan=False):
    """Build a label-based entity ID (matches YAML package format)."""
    domain = "input_number" if is_fan else "input_boolean"
    safe_label = sanitize_label(label)
    safe_room = sanitize_label(room_key)
    return f"{domain}.iotics_{safe_room}_{safe_label}"

def friendly_name(room_key, label):
    """Human-readable name for the entity."""
    nr = room_key.replace("_", " ").title()
    nl = label.replace("_", " ").title()
    # Remove duplication: "Kitchen Kitchen Fan" -> "Kitchen Fan"
    if nl.lower().startswith(nr.lower().split()[0]):
        nl = nl[len(nr.split()[0]):].strip()
    return f"{nr} {nl}" if nl else nr

def room_display(rk):
    return rk.replace("_", " ").title()

# ── HTTP device control ────────────────────────────────────────────────────
def send_http(ip, button, status):
    try:
        urllib.request.urlopen(f"http://{ip}/action?button={button}&status={status}", timeout=3)
        log.info("[HTTP] %s/%s -> %s", ip, button, status)
        return True
    except Exception as e:
        log.warning("[HTTP ERR] %s/%s: %s", ip, button, e)
        return False

# ── ARP IP detection ───────────────────────────────────────────────────────
def seed_ips():
    """Populate IP_CACHE from the ARP cache."""
    try:
        r = subprocess.run(["arp", "-an"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            m = re.search(r"\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([0-9a-fA-F:]+)", line)
            if m:
                ip, mac = m.group(1), m.group(2).replace(":", "").lower()
                IP_CACHE[mac] = ip
                if mac in DEVICES:
                    DEVICES[mac]["ip"] = ip
        log.info("[IP] Cache scan: %d IPs from ARP", len(IP_CACHE))
    except Exception as e:
        log.warning("[IP] Scan failed: %s", e)

def detect_ip(token):
    """Fast IP lookup."""
    cached = IP_CACHE.get(token)
    if cached:
        return cached
    try:
        r = subprocess.run(["arp", "-an"], capture_output=True, text=True, timeout=3)
        for line in r.stdout.splitlines():
            m = re.search(r"\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([0-9a-fA-F:]+)", line)
            if m:
                ip, mac = m.group(1), m.group(2).replace(":", "").lower()
                if mac == token.lower():
                    IP_CACHE[token] = ip
                    return ip
    except:
        pass
    return None

# ── Entity management ──────────────────────────────────────────────────────
def ensure_entity(eid, state, friendly, is_fan=False):
    """Create or update an entity. Never toggles if already set."""
    existing = ha_get(f"states/{eid}")
    if existing:
        # Update attributes but preserve current state
        attrs = dict(existing.get("attributes", {}))
        attrs["friendly_name"] = friendly
        if is_fan:
            attrs.update({"min": 1, "max": 4, "step": 1, "mode": "slider"})
        ha_post(f"states/{eid}", {
            "state": existing["state"],
            "attributes": attrs,
        })
    else:
        # Create new entity with given state
        attrs = {"friendly_name": friendly}
        if is_fan:
            attrs.update({"min": 1, "max": 4, "step": 1, "mode": "slider"})
        ha_post(f"states/{eid}", {"state": state, "attributes": attrs})

def cleanup_orphans(active_eids):
    """Delete iotics entities that no longer exist in the cloud."""
    try:
        states = ha_get("states") or []
    except:
        return
    orphans = [s["entity_id"] for s in states
               if "iotics" in s.get("entity_id", "").lower()
               and s["entity_id"] not in active_eids
               and not s["entity_id"].startswith("update.")]
    if not orphans:
        return
    log.info("[CLEANUP] Removing %d orphan entities", len(orphans))
    deleted = 0
    for eid in sorted(orphans):
        try:
            req = urllib.request.Request(
                f"{HASS_URL}/api/states/{eid}",
                method="DELETE",
                headers={"Authorization": f"Bearer {HASS_TOKEN}"},
            )
            with urllib.request.urlopen(req, timeout=10):
                deleted += 1
        except:
            pass
    log.info("[CLEANUP] Deleted %d orphans", deleted)

# ── Cloud API Polling (READ-ONLY) ──────────────────────────────────────────
def cloud_poll_loop():
    """
    Poll the Iotics cloud API every 5 seconds for current device states.
    This is READ-ONLY — never sends commands to devices.
    Auto-discovers all devices, buttons, and labels dynamically.
    """
    log.info("[CLOUD] Starting cloud poll loop (5s interval, no hardcoded mappings)")
    
    # Wait a moment for HA to be ready
    time.sleep(5)
    
    while True:
        try:
            # 1. Login
            data = json.dumps({
                "emailid": IOTICS_EMAIL, "password": IOTICS_PASSWORD,
                "action": "login", "appid": IOTICS_APPID,
                "device_token": "iotics-ha-addon",
                "source": "mobile", "os": "ios",
            }).encode()
            req = urllib.request.Request(
                "https://api.iotics.io/user/login",
                data=data, headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                result = json.loads(r.read())
            session = result.get("response", {}).get("session", "")
            if not session:
                log.warning("[CLOUD] Login failed (check your email/password)")
                time.sleep(30)
                continue

            # 2. Get device states (auto-discovers everything)
            data = json.dumps({
                "session": session, "appid": IOTICS_APPID,
                "emailid": IOTICS_EMAIL, "action": "getdevices",
            }).encode()
            req = urllib.request.Request(
                "https://api.iotics.io/device/",
                data=data, headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                result = json.loads(r.read())
            devices_data = result.get("response", {}).get("data", [])

            if not devices_data:
                time.sleep(5)
                continue

            # 3. Process each device
            active_entities = set()
            new_devices_found = 0

            for d in devices_data:
                # Get the device MAC (token) and hardware name
                mac = d.get("mac", "").replace(":", "").lower()
                hwname = d.get("hardwarename", "").strip()
                if not mac:
                    continue

                # Create a clean room key from the device name
                room_key = sanitize_label(hwname) if hwname else f"device_{mac[-4:]}"

                # Ensure device is in our state
                if mac not in DEVICES:
                    ip = detect_ip(mac)
                    DEVICES[mac] = {"room_key": room_key, "ip": ip, "buttons": {}}
                    new_devices_found += 1
                    log.info("[CLOUD] New device: %s (%s)", hwname, mac)
                else:
                    # Update room_key if name changed
                    if DEVICES[mac]["room_key"] != room_key:
                        log.info("[CLOUD] Device '%s' renamed: %s -> %s",
                                 mac, DEVICES[mac]["room_key"], room_key)
                        DEVICES[mac]["room_key"] = room_key

                dev = DEVICES[mac]
                rk = dev["room_key"]

                # 4. Process each button/control
                for btn, info in d.get("switches", {}).items():
                    if btn.startswith("dl"):
                        continue  # Skip dimmers

                    label_raw = info.get("label", btn).strip()
                    label = sanitize_label(label_raw) if label_raw != btn else label_raw
                    status = info.get("status", "0")

                    # Determine type
                    is_fan = btn in ("l1", "l2")
                    is_custom = False

                    # If label has meaningful text, it's a custom label
                    if label != btn and re.fullmatch(r'[a-z][a-z0-9_]+', label):
                        is_custom = True

                    # Use label from cloud if it's custom, otherwise use button name
                    display_label = label if is_custom else btn

                    # Build entity ID
                    eid = build_eid(rk, display_label, is_fan)
                    fn = friendly_name(rk, display_label)
                    ha_state = str(status) if is_fan else ("on" if str(status) == "1" else "off")

                    # Create/update entity
                    ensure_entity(eid, ha_state, fn, is_fan)
                    active_entities.add(eid)

                    # Update ENTITY_CACHE so WS listener doesn't re-fire commands
                    ENTITY_CACHE[eid] = json.dumps({"state": ha_state})

                    # Track button in device state
                    if btn not in dev["buttons"]:
                        dev["buttons"][btn] = {
                            "label": display_label,
                            "type": "fan" if is_fan else "switch",
                            "is_fan": is_fan,
                        }
                    else:
                        # Update label if renamed
                        if dev["buttons"][btn].get("label") != display_label:
                            dev["buttons"][btn]["label"] = display_label

            # 5. Clean up orphan entities
            cleanup_orphans(active_entities)

            if new_devices_found:
                log.info("[CLOUD] Discovered %d new devices. Total: %d devices, %d buttons",
                         new_devices_found, len(DEVICES),
                         sum(len(d["buttons"]) for d in DEVICES.values()))

            # Push dashboard on first run and periodically
            if not ENTITY_CACHE or new_devices_found:
                threading.Thread(target=push_dashboard, daemon=True).start()

            time.sleep(5)

        except Exception as e:
            log.warning("[CLOUD] Poll failed: %s", e)
            time.sleep(10)

# ── HA WebSocket: command listener ─────────────────────────────────────────
def ws_listener():
    """Listen for HA state changes and fire commands to Iotics devices."""
    import websockets.sync.client as ws_client
    grace_period = 10  # seconds to ignore startup events
    while True:
        try:
            ws = ws_client.connect(
                f"{HASS_URL.replace('http://', 'ws://').replace('https://', 'wss://')}/api/websocket",
                additional_headers={"Authorization": f"Bearer {HASS_TOKEN}"},
                open_timeout=10,
            )
            msg = json.loads(ws.recv())
            if msg.get("type") == "auth_required":
                ws.send(json.dumps({"type": "auth", "access_token": HASS_TOKEN}))
                auth = json.loads(ws.recv())
                if auth.get("type") != "auth_ok":
                    log.warning("[WS] Auth failed")
                    ws.close()
                    time.sleep(5)
                    continue

            ws.send(json.dumps({"id": 1, "type": "subscribe_events", "event_type": "state_changed"}))
            sub = json.loads(ws.recv())
            if not sub.get("success"):
                log.warning("[WS] Subscribe failed")
                ws.close()
                time.sleep(5)
                continue

            log.info("[WS] Connected and listening for state changes")
            connected_at = time.time()

            while True:
                raw = ws.recv()
                try:
                    evt = json.loads(raw)
                except:
                    continue

                event = evt.get("event", {})
                data = event.get("data", {})
                eid = data.get("entity_id", "")
                if "iotics" not in eid.lower():
                    continue

                new = data.get("new_state", {})
                old = data.get("old_state", {})
                nv = new.get("state", "") if new else ""
                ov = old.get("state", "") if old else ""
                if not nv or nv == ov:
                    continue

                # Grace period: ignore changes right after connect
                if time.time() - connected_at < grace_period:
                    ENTITY_CACHE[eid] = json.dumps(new) if new else "{}"
                    continue

                # Skip if this is an MQTT/cloud echo (cached state matches)
                cached = ENTITY_CACHE.get(eid)
                cached_state = ""
                if cached:
                    try:
                        cached_state = json.loads(cached).get("state", "")
                    except:
                        pass
                if nv == cached_state:
                    continue

                # Update cache
                ENTITY_CACHE[eid] = json.dumps(new) if new else "{}"

                # Parse entity ID to find device + button
                parts = eid.split(".")
                if len(parts) < 2:
                    continue
                ename = parts[1]
                if not ename.startswith("iotics_"):
                    continue
                is_fan = parts[0] == "input_number"

                # Extract room and label from entity name
                ebody = ename[len("iotics_"):]
                # Find which device this belongs to by trying room_key prefixes
                matched_token = None
                matched_btn = None
                for token, dev in list(DEVICES.items()):
                    rk = dev.get("room_key", "")
                    if not rk:
                        continue
                    rk_slug = sanitize_label(rk)
                    # Check if entity name starts with room prefix
                    if not ebody.startswith(rk_slug + "_") and ebody != rk_slug:
                        # Try without room prefix
                        continue
                    # Extract the label part
                    label_part = ebody[len(rk_slug) + 1:] if ebody.startswith(rk_slug + "_") else ""
                    # Find matching button
                    for btn, bi in dev.get("buttons", {}).items():
                        if bi.get("label", "").lower() == label_part.lower():
                            matched_token = token
                            matched_btn = btn
                            break
                    if matched_token:
                        break

                if not matched_token:
                    continue

                # Execute command
                ip = DEVICES[matched_token].get("ip")
                if not ip:
                    ip = detect_ip(matched_token)
                    if ip:
                        DEVICES[matched_token]["ip"] = ip
                    else:
                        log.debug("[WS] No IP for %s", matched_token)
                        continue

                # Cooldown check
                now = time.time()
                last = LAST_CMD.get(eid, 0)
                if now - last < CMD_COOLDOWN:
                    continue
                LAST_CMD[eid] = now

                if is_fan:
                    try:
                        speed = int(float(nv))
                        if 1 <= speed <= 4:
                            # Fan speed commands still need MQTT if available
                            # For bridge-only mode, try HTTP with l1
                            send_http(ip, "l1", str(speed))
                    except (ValueError, TypeError):
                        pass
                else:
                    cmd = "1" if nv == "on" else "0"
                    if matched_btn:
                        send_http(ip, matched_btn, cmd)

        except Exception as e:
            log.warning("[WS] Error: %s", e)
            time.sleep(3)

# ── Dashboard generator ────────────────────────────────────────────────────
def gen_dashboard():
    """Generate a Lovelace dashboard from discovered devices."""
    cards = []
    room_order = sorted(set(dev.get("room_key", "") for dev in DEVICES.values()),
                        key=lambda x: x)

    states = ha_get("states") or []
    rooms = {}

    for s in states:
        eid = s.get("entity_id", "")
        if "iotics" not in eid or ("input_boolean." not in eid and "input_number." not in eid):
            continue
        parts = eid.split(".")
        if len(parts) < 2:
            continue
        ename = parts[1]
        if not ename.startswith("iotics_"):
            continue
        ebody = ename[len("iotics_"):]

        fn = s.get("attributes", {}).get("friendly_name", "")
        is_fan = parts[0] == "input_number"

        # Find room by label prefix matching
        matched_rk = ""
        for token, dev in DEVICES.items():
            rk = dev.get("room_key", "")
            rk_slug = sanitize_label(rk)
            if ebody.startswith(rk_slug + "_") or ebody == rk_slug:
                matched_rk = rk
                break
        if not matched_rk:
            continue

        if matched_rk not in rooms:
            rooms[matched_rk] = []
        rooms[matched_rk].append({
            "eid": eid, "fn": fn, "is_fan": is_fan,
            "label": ebody[len(sanitize_label(matched_rk)) + 1:] if ebody.startswith(sanitize_label(matched_rk) + "_") else ebody,
        })

    for rk in room_order:
        if rk not in rooms or not rooms[rk]:
            continue
        ents = sorted(rooms[rk], key=lambda x: (x["is_fan"], x["label"]))
        cards.append({"type": "heading", "heading": room_display(rk)})
        row = []
        for e in ents:
            if e["is_fan"]:
                # Fan speed: show as 4 speed buttons
                fan_buttons = []
                for i in range(1, 5):
                    fan_buttons.append({
                        "type": "button",
                        "entity": e["eid"],
                        "name": str(i),
                        "tap_action": {
                            "action": "call-service",
                            "service": "input_number.set_value",
                            "service_data": {"entity_id": e["eid"], "value": i},
                        },
                        "show_state": False,
                        "icon": "mdi:fan",
                        "state_color": True,
                    })
                row.append({"type": "horizontal-stack", "cards": fan_buttons})
            else:
                # Regular switch
                name = e["fn"]
                rk_title = room_display(rk)
                if rk_title in name:
                    name = name.replace(rk_title, "").strip()
                row.append({"type": "entity", "entity": e["eid"], "name": name or e["fn"]})
            if len(row) >= 4:
                cards.append({"type": "grid", "cards": row, "columns": 4})
                row = []
        if row:
            cards.append({"type": "grid", "cards": row, "columns": len(row)})

    if not cards:
        cards.append({"type": "markdown", "content": "Waiting for Iotics devices..."})

    return {"title": "Iotics Smart Home", "path": "iotics", "icon": "mdi:smart-home", "cards": cards}

# ── Dashboard push ─────────────────────────────────────────────────────────
def push_dashboard():
    """Push the dashboard to HA via WebSocket."""
    config = gen_dashboard()
    room_count = len([c for c in config.get("cards", []) if c.get("type") == "heading"])

    import websockets.sync.client as ws_client
    try:
        ws = ws_client.connect(
            f"{HASS_URL.replace('http://', 'ws://').replace('https://', 'wss://')}/api/websocket",
            additional_headers={"Authorization": f"Bearer {HASS_TOKEN}"},
            open_timeout=10,
        )
        msg = json.loads(ws.recv())
        if msg.get("type") == "auth_required":
            ws.send(json.dumps({"type": "auth", "access_token": HASS_TOKEN}))
            auth = json.loads(ws.recv())
            if auth.get("type") != "auth_ok":
                ws.close()
                return

        # Get current config
        ws.send(json.dumps({"id": 1, "type": "lovelace/config"}))
        resp = json.loads(ws.recv())
        if resp.get("success") and resp.get("result"):
            cur = resp["result"]
            views = cur.get("views", []) if isinstance(cur, dict) else (cur if isinstance(cur, list) else [])
        else:
            views = []

        # Merge/update the Iotics view
        replaced = False
        for i, v in enumerate(views):
            if isinstance(v, dict) and v.get("path") == "iotics":
                views[i] = config
                replaced = True
                break
        if not replaced:
            views.append(config)

        # Save
        ws.send(json.dumps({
            "id": 2, "type": "lovelace/config/save",
            "config": {"views": views},
        }))
        save = json.loads(ws.recv())
        if save.get("success"):
            log.info("[LOVELACE] Dashboard pushed: %d rooms", room_count)
        else:
            log.warning("[LOVELACE] Save failed: %s", save)
        ws.close()
    except Exception as e:
        log.warning("[LOVELACE] Push failed: %s", e)

# ── Main ────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 60)
    log.info("Iotics Smart Home Bridge — HA Add-on Edition v1.0")
    log.info("=" * 60)

    if not IOTICS_EMAIL or not IOTICS_PASSWORD:
        log.error("IOTICS_EMAIL and IOTICS_PASSWORD must be set!")
        log.error("Set them as environment variables or in the HA add-on config.")
        sys.exit(1)

    if not HASS_TOKEN:
        log.error("HASS_TOKEN not found! This add-on requires HA supervisor API access.")
        sys.exit(1)

    log.info("Iotics account: %s", IOTICS_EMAIL)
    log.info("HA URL: %s", HASS_URL)
    log.info("HA token: %d chars", len(HASS_TOKEN))

    # Start background IP detection
    threading.Thread(target=seed_ips, daemon=True).start()

    # Start cloud API poll loop (this does everything: discovery, sync, dashboard)
    cloud_thread = threading.Thread(target=cloud_poll_loop, daemon=True)
    cloud_thread.start()

    # Start WS listener for user commands
    ws_thread = threading.Thread(target=ws_listener, daemon=True)
    ws_thread.start()

    log.info("[READY] All threads started. Listening for device changes...")
    log.info("[READY] Dashboard will appear in HA automatically.")
    log.info("[READY] Log file: %s", LOG_PATH)

    # Keep main thread alive
    try:
        while True:
            time.sleep(10)
            # Periodic dashboard refresh (every 5 min) and heartbeat
            room_cfg = gen_dashboard()
            room_count = len([c for c in room_cfg.get("cards", []) if c.get("type") == "heading"])
            btn_count = sum(len(d.get("buttons", {})) for d in DEVICES.values())
            log.info("[HEARTBEAT] %d rooms, %d devices, %d buttons",
                     room_count, len(DEVICES), btn_count)
    except KeyboardInterrupt:
        log.info("Shutting down...")
        sys.exit(0)

if __name__ == "__main__":
    main()
