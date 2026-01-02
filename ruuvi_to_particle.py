"""
ruuvi_to_particle.py

Scan for Ruuvi Tag BLE advertisements, decode sensor readings, and publish
them to the Particle Cloud using the `pyparticle` package.

Dependencies:
- bleak (BLE library)
- pyparticle (this repo; install editable or pip install -e .)

Install dependencies in your virtualenv:

    /home/besir/pyparticle/.venv/bin/pip install bleak

Usage:
    export PARTICLE_TOKEN=your_particle_token_here
    export RUUVI_MAC=AA:BB:CC:DD:EE:FF    # optional - scan all if not set
    /home/besir/pyparticle/.venv/bin/python ruuvi_to_particle.py

Behavior:
- Scans for BLE advertisements from Ruuvi tags (manufacturer data format).
- Decodes temperature, humidity, pressure when present (supports Ruuvi v2/3 URL and RAW formats minimally).
- Publishes readings to Particle Cloud using `pyparticle.Particle.publish_event` with event name `ruuvi_data`.

Note: This script relies on the host's BLE adapter and permissions. On Linux you may need
`sudo` or set appropriate capabilities for the Python binary (e.g. `sudo setcap 'cap_net_raw,cap_net_admin+eip' $(which python3)`).

"""

import os
import asyncio
import struct
import binascii
import time
from typing import Optional, Dict
import warnings

try:
    from bleak import BleakScanner
except Exception as e:
    raise RuntimeError("`bleak` is required. Install with: pip install bleak")

import pyparticle as pp

# Configuration
# Hardcoded token for prototyping. Replace with env var in production.
PARTICLE_TOKEN = "ddf9805d477d335e7134bbc9feac3535a98c58f6"
TARGET_MAC = os.environ.get('RUUVI_MAC')  # optional, uppercase or lowercase MAC

# Normalize TARGET_MAC for comparison (remove colons/spaces and lowercase).
# If not provided (None), the script scans all devices.
if TARGET_MAC:
    norm_target_mac = ''.join(c for c in TARGET_MAC if c.isalnum()).lower()
else:
    norm_target_mac = None
PUBLISH_EVENT_NAME = os.environ.get('PARTICLE_RUUVI_EVENT', 'ruuvi_data')

if not PARTICLE_TOKEN:
    raise SystemExit('Please set $PARTICLE_TOKEN to your Particle access token')

particle = pp.Particle(access_token=PARTICLE_TOKEN)

# Minimal Ruuvi RAWv2 parser (0x0499 company ID) for manufacturer data format 0x03 / 0x16
# Ruuvi RAWv2 payload format (24 bytes) and RAWv3/URL are more complex; this parser
# handles common RAW formats used by tags broadcasting environmental data.

def parse_ruuvi_manufacturer_data(data: bytes) -> Optional[Dict]:
    """Try to parse Ruuvi manufacturer data from bytes. Returns dict or None."""
    # Many Ruuvi tags use Nordic UART or manufacturer data in different formats.
    # Here we check for the common Ruuvi RAW (0x0499 as company ID) pattern. If not
    # present, return None.
    if len(data) < 3:
        return None

    # Some adverts include a leading company id (0x99 0x04 little-endian)
    # and then a payload. Look for 0x99 0x04 sequence.
    try:
        hexs = binascii.hexlify(data).decode()
    except Exception:
        return None

    # Look for 9904 hex sequence in little-endian or big-endian
    if '9904' in hexs:
        # find index
        idx = hexs.find('9904')
        # convert index in hex chars to byte index
        byte_idx = idx // 2
        payload = data[byte_idx + 2:]
    else:
        # If no company id present, assume whole payload could be Ruuvi RAW
        payload = data

    # RAWv2/RAWv3-like payloads commonly contain a data format byte followed
    # by temperature (two bytes), humidity (one byte) and pressure (two bytes).
    # Because manufacturers and BLE stacks sometimes present bytes in
    # different orders, try both endianness and a couple of reasonable
    # scale factors and pick a plausible decoding (temperature within
    # -40..85 C, humidity 0..100 %, pressure 300..1200 hPa).
    if len(payload) >= 8:
        fmt = payload[0]
        if fmt in (2, 3, 4, 5, 6, 8):
            try:
                # bytes for trial decoding
                t_bytes = payload[1:3]
                h_byte = payload[3]
                p_bytes = payload[4:6]

                candidates = []
                for endian in ('>', '<'):
                    try:
                        t_raw = struct.unpack(endian + 'h', t_bytes)[0]
                    except Exception:
                        continue
                    for t_scale in (100.0, 200.0, 1000.0):
                        temperature = t_raw / t_scale
                        # humidity is often a single byte 0..100
                        humidity = float(h_byte)
                        try:
                            p_raw = struct.unpack(endian + 'H', p_bytes)[0]
                        except Exception:
                            continue
                        for p_scale in (10.0, 1.0):
                            pressure = p_raw / p_scale
                            # sanity checks for plausible environmental ranges
                            if -40.0 <= temperature <= 85.0 and 0.0 <= humidity <= 100.0 and 300.0 <= pressure <= 1200.0:
                                candidates.append((temperature, humidity, pressure, endian, t_scale, p_scale))

                if candidates:
                    # prefer the first plausible candidate (typically big-endian/100)
                    temperature, humidity, pressure, endian, t_scale, p_scale = candidates[0]
                    return {
                        'format': fmt,
                        'temperature': round(temperature, 2),
                        'humidity': round(humidity, 2),
                        'pressure': round(pressure, 2)
                    }
            except Exception:
                return None

    return None


async def scan_and_publish(duration: int = 10):
    """Scan for BLE advertisements for `duration` seconds and publish any parsed Ruuvi data.

    Only Ruuvi-like manufacturer payloads are considered. If none are found the
    function prints a short message and exits.
    """
    print(f"Scanning for Ruuvi adverts for {duration}s...")
    # Use return_adv=True to get AdvertisementData alongside BLEDevice (newer bleak).
    # Fall back to the older behavior if return_adv is not supported.
    try:
        devices_raw = await BleakScanner.discover(timeout=duration, return_adv=True)
    except TypeError:
        devices_raw = await BleakScanner.discover(timeout=duration)

    found = 0
    for item in devices_raw:
        # item may be (device, advertisement_data) on newer bleak, or BLEDevice on older bleak
        # Some backends return (device, adv) tuples, some return BLEDevice objects,
        # and some may return simple address strings. Normalize these cases.
        if isinstance(item, tuple) and len(item) == 2:
            d, adv = item
        elif isinstance(item, str):
            # item is an address string; try to resolve to a device object
            addr = item
            adv = None
            try:
                d = await BleakScanner.find_device_by_address(addr, timeout=1.0)
            except Exception:
                d = None
        else:
            d = item
            adv = None

        # Defensive: some backends/versions may return unexpected entries; skip them
        if d is None or not hasattr(d, 'address'):
            continue

        # If a target MAC was provided, skip devices that do not match it.
        if norm_target_mac:
            dev_mac = ''.join(c for c in (d.address or '') if c.isalnum()).lower()
            if dev_mac != norm_target_mac:
                continue

        # Retrieve manufacturer data (prefer AdvertisementData when available)
        try:
            if adv and getattr(adv, 'manufacturer_data', None):
                m = adv.manufacturer_data
            else:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', FutureWarning)
                    m = d.metadata.get('manufacturer_data') if d.metadata else None
        except Exception:
            m = None

        # If no manufacturer data, skip
        if not m:
            continue

        # Pick a manufacturer payload to check and skip iBeacon payloads
        mfg = None
        for k, v in m.items():
            try:
                starts = bytes(v[:2])
            except Exception:
                starts = None
            if starts == b"\x02\x15":
                # iBeacon — not a Ruuvi payload
                continue
            mfg = v
            break

        if not mfg:
            continue

        # Dump raw manufacturer payload for debugging to inspect exact bytes
        try:
            raw_hex = binascii.hexlify(bytes(mfg)).decode()
        except Exception:
            raw_hex = str(mfg)
        print('  Raw manufacturer bytes:', raw_hex)
        parsed = parse_ruuvi_manufacturer_data(bytes(mfg))
        if not parsed:
            continue

        # Parsed Ruuvi reading — publish and report
        found += 1
        payload = parsed
        payload.update({'mac': d.address, 'name': d.name})
        print('Found Ruuvi-like tag:', d.address, '->', payload)
        try:
            data_str = f"mac={d.address},temp={payload.get('temperature')},humidity={payload.get('humidity')},pressure={payload.get('pressure')}"
            resp = particle.publish_event(PUBLISH_EVENT_NAME, data=data_str, is_private=False)
            print('Published to Particle:', resp)
        except Exception as e:
            print('Failed to publish to Particle:', e)

    if found == 0:
        print('No Ruuvi-like adverts parsed. Devices discovered:', len(devices_raw))


async def inspect_mac(mac: str, duration: int = 10):
    """Scan for the given MAC and print raw advertisement bytes and trial decodings.

    This helps diagnose parsing issues (endianness/scaling)."""
    print(f"Inspecting MAC {mac} for {duration}s...")
    norm = ''.join(c for c in mac if c.isalnum()).lower()
    # Try to get advertisement data when possible
    try:
        devices_raw = await BleakScanner.discover(timeout=duration, return_adv=True)
    except TypeError:
        devices_raw = await BleakScanner.discover(timeout=duration)

    for item in devices_raw:
        if isinstance(item, tuple) and len(item) == 2:
            d, adv = item
        else:
            d = item
            adv = None

        # Some bleak versions/platforms may return unexpected types; guard against that
        if not hasattr(d, 'address'):
            # skip entries that don't expose an address
            continue

        dev_mac = ''.join(c for c in (d.address or '') if c.isalnum()).lower()
        if dev_mac != norm:
            continue

        print('\nFound device:', d.address, 'name:', d.name, 'rssi:', getattr(d, 'rssi', 'N/A'))

        # Manufacturer data from adv or metadata
        m = None
        if adv and getattr(adv, 'manufacturer_data', None):
            m = adv.manufacturer_data
        else:
            m = d.metadata.get('manufacturer_data') if d.metadata else None

        if m:
                for k, v in m.items():
                    raw_hex = binascii.hexlify(v).decode()
                    print(f'  Manufacturer id: 0x{k:04x} raw: {raw_hex}')
                # Try a few trial decodings on the payload bytes
                b = bytes(v)
                print('  Raw bytes:', b)
                # If this looks like an Apple iBeacon payload (0x02 0x15), tell the user
                if raw_hex.startswith('0215'):
                        print('  Note: this payload looks like an Apple iBeacon advertisement (starts with 0x02 0x15) and is not a Ruuvi tag.')
                if len(b) >= 6:
                    # Try signed big/little endian int16 /100 and /1000
                    try:
                        be = struct.unpack('>h', b[1:3])[0]
                        le = struct.unpack('<h', b[1:3])[0]
                        print('  temp_be/100:', be / 100.0)
                        print('  temp_be/1000:', be / 1000.0)
                        print('  temp_le/100:', le / 100.0)
                        print('  temp_le/1000:', le / 1000.0)
                    except Exception:
                        pass
                    try:
                        pres_be = struct.unpack('>H', b[4:6])[0]
                        pres_le = struct.unpack('<H', b[4:6])[0]
                        print('  pres_be/10:', pres_be / 10.0)
                        print('  pres_be/100:', pres_be / 100.0)
                        print('  pres_le/10:', pres_le / 10.0)
                    except Exception:
                        pass

        # show service data if present
        if adv and getattr(adv, 'service_data', None):
            for sid, sbytes in adv.service_data.items():
                print('  Service data', sid, binascii.hexlify(sbytes).decode())
        else:
            svc = d.metadata.get('service_data') if d.metadata else None
            if svc:
                for sid, sbytes in svc.items():
                    print('  Service data', sid, binascii.hexlify(sbytes).decode())

        return

    print('Device with MAC not found in scan period')


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Scan Ruuvi tags and publish to Particle Cloud')
    parser.add_argument('--scan-time', '-t', type=int, default=10, help='scan duration in seconds')
    parser.add_argument('--inspect-mac', help='Inspect a specific MAC and print raw bytes + trial decodes')
    # keep interface minimal: only scan for Ruuvi tags and publish them
    args = parser.parse_args()

    try:
        if args.inspect_mac:
            asyncio.run(inspect_mac(args.inspect_mac, duration=args.scan_time))
        else:
            asyncio.run(scan_and_publish(duration=args.scan_time))
    except KeyboardInterrupt:
        print('Interrupted')


if __name__ == '__main__':
    main()
