#!/usr/bin/env python3
import asyncio
import struct
from bleak import BleakScanner
import binascii
from typing import Optional, Dict
import pyparticle as pp

# RuuviTag manufacturer ID (0x0499)
# This is the standard Bluetooth SIG assigned Company Identifier for Ruuvi Innovations Ltd.
RUUVI_MANUFACTURER_ID = 0x0499

async def main():
    # Initialize Particle Cloud connection
    particle_token = "ddf9805d477d335e7134bbc9feac3535a98c58f6"
    particle = pp.Particle(access_token=particle_token)

    while True:
        print("Scanning for RuuviTags...")
        # Discover devices with advertisement data
        # return_adv=True is important to get manufacturer_data
        devices_raw = await BleakScanner.discover(return_adv=True)

        found_ruuvi_tags = 0
        # In newer Bleak versions, discover(return_adv=True) returns a dict {mac: (device, adv)}.
        # We need to iterate over the values to get the tuples.
        for item in (devices_raw.values() if isinstance(devices_raw, dict) else devices_raw):
            # item is a tuple of (BLEDevice, AdvertisementData)
            device, advertisement_data = item

            # Check if manufacturer data exists and if it contains Ruuvi's ID
            if advertisement_data.manufacturer_data:
                for manufacturer_id, data in advertisement_data.manufacturer_data.items():
                    if manufacturer_id == RUUVI_MANUFACTURER_ID:
                        found_ruuvi_tags += 1
                        print(f"Found RuuviTag: {device.address}")
                        print(f"  Name: {device.name}")
                        print(f"  RSSI: {advertisement_data.rssi} dBm") # Signal strength
                        
                        # Attempt to parse the RuuviTag data
                        parsed_data = parse_ruuvi_manufacturer_data(data)
                        if parsed_data:
                            print(f"  Parsed Data:")
                            for key, value in parsed_data.items():
                                print(f"    {key}: {value}")

                            # Publish to Particle Cloud
                            try:
                                # Format: mac=XX,temp=XX,humidity=XX,pressure=XX
                                payload_str = f"mac={device.address},temp={parsed_data['temperature_c']},humidity={parsed_data['humidity_rh']},pressure={parsed_data['pressure_hpa']}"
                                print(f"  Publishing event 'ruuvi_data': {payload_str}")
                                particle.publish_event('ruuvi_data', data=payload_str, is_private=True)
                                print("  Success: Published to Particle Cloud.")
                            except Exception as e:
                                print(f"  Error publishing to Particle: {e}")
                        else:
                            print(f"  Manufacturer Data (Ruuvi, raw hex): {binascii.hexlify(data).decode()}")
                            print("  (Could not parse data. Ensure it's a supported Ruuvi RAW format.)")
                        print("-" * 30)

        if found_ruuvi_tags == 0:
            print("No RuuviTags found during the scan.")
        else:
            print(f"Scan complete. Found {found_ruuvi_tags} RuuviTag(s).")
        
        # Wait for 60 seconds before the next scan
        await asyncio.sleep(60)


def parse_ruuvi_manufacturer_data(data: bytes) -> Optional[Dict]:
    """
    Parses RuuviTag manufacturer data.
    Supports Ruuvi RAWv2/v3-like formats for temperature, humidity, and pressure.
    """
    if len(data) < 3:
        return None

    # Ruuvi data often starts with a format byte.
    # For RAWv2/v3, the format byte is typically 0x03 or 0x05.
    # The manufacturer ID (0x0499) is usually prepended by the BLE stack,
    # so we're looking at the payload *after* the manufacturer ID.
    # The `data` parameter here is already the payload after the 0x0499 ID.

    # Check for the data format byte
    data_format = data[0]

    # This parser is a simplified version for common RAW formats (e.g., 0x03, 0x05)
    # It assumes a structure where temperature, humidity, and pressure are present
    # in a specific byte order and scaling.
    # For a full, robust parser, consider using the official RuuviTag Python library
    # or a more comprehensive implementation.

    # Example for RuuviTag RAWv2/v3-like format (format 0x03 or 0x05)
    # This is a common structure:
    # byte 0: data format (e.g., 0x03, 0x05)
    # byte 1-2: temperature (signed 16-bit integer, scaled)
    # byte 3: humidity (unsigned 8-bit integer, scaled)
    # byte 4-5: pressure (unsigned 16-bit integer, scaled)
    
    # Format 5 (RAWv2)
    if data_format == 0x05 and len(data) >= 24:
        try:
            # Temp: 16-bit signed, 0.005 step
            temp_raw = struct.unpack('>h', data[1:3])[0]
            temperature = temp_raw * 0.005
            # Humidity: 16-bit unsigned, 0.0025 step
            hum_raw = struct.unpack('>H', data[3:5])[0]
            humidity = hum_raw * 0.0025
            
            # Pressure: 16-bit unsigned, +50000 Pa
            pres_raw = struct.unpack('>H', data[5:7])[0]
            pressure = (pres_raw + 50000) / 100.0 # Pa to hPa

            return {
                'format': data_format,
                'temperature_c': round(temperature, 2),
                'humidity_rh': round(humidity, 2),
                'pressure_hpa': round(pressure, 2),
                'raw_data_hex': binascii.hexlify(data).decode()
            }
        except struct.error:
            pass

    # Format 3 (RAWv1)
    elif data_format == 0x03 and len(data) >= 14:
        try:
            humidity = data[1] * 0.5
            temp_whole = struct.unpack('b', data[2:3])[0]
            temp_frac = data[3]
            temperature = temp_whole + (temp_frac / 100.0)
            pres_raw = struct.unpack('>H', data[4:6])[0]
            pressure = (pres_raw + 50000) / 100.0
            
            return {
                'format': data_format,
                'temperature_c': round(temperature, 2),
                'humidity_rh': round(humidity, 2),
                'pressure_hpa': round(pressure, 2),
                'raw_data_hex': binascii.hexlify(data).decode()
            }
        except struct.error:
            pass

    return None # Return None if format is not recognized or parsing fails


if __name__ == "__main__":
    asyncio.run(main())
