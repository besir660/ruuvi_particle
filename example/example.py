# -*- coding: utf-8 -*-

import pyparticle as pp
import sys
import os

# Read the access token stored in a file
access_token = "ddf9805d477d335e7134bbc9feac3535a98c58f6"


# Initiatise the Particle object using the cache access token
particle = pp.Particle(access_token=access_token)

try:
    devices = particle.list_devices()
except:
    # An exception has been raised indicating that the access token is out of date use the login details to refresh the token
    particle = pp.Particle('username', 'password')
    devices = particle.list_devices()

if len(devices) == 0:
    print('No devices found')
    sys.exit()

# Select device by name to avoid indexing issues. You can override the name
# by setting the environment variable `PARTICLE_DEVICE_NAME`.
target_name = os.environ.get('PARTICLE_DEVICE_NAME', 'Venturion_Control')

print('Found %d devices' % len(devices))

# Try to find a device matching the target name (case-insensitive)
device = None
for d in devices:
    if d.get('name', '').lower() == target_name.lower() or d.get('id', '') == target_name:
        device = d
        break

if device is None:
    print("Device named '%s' not found. Available devices:" % target_name)
    for d in devices:
        print(" - %s (id: %s)" % (d.get('name'), d.get('id')))
    sys.exit(2)

print('Selected device: %s' % device['name'])

# The device exposes the variables 'humidity', 'temp_dht', 'temp_bmp' and 'pressure'
humidity = particle.get_variable(device['id'], 'Humidity')
temp     = particle.get_variable(device['id'], 'Temperature')


# Print the variables
print('Humidity: %.2f%%' % humidity['result'])
print('Temperature: %.2f°C' % temp['result'])

# Publish an event with the sensor data
event_data = 'temp=%.2f,humidity=%.2f' % (temp['result'], humidity['result'])
try:
    result = particle.publish_event('sensor_data', data=event_data, is_private=True)
    if result.get('ok'):
        print('✓ Event published successfully')
        print('  Event: sensor_data')
        print('  Data: %s' % event_data)
    else:
        print('Failed to publish event: %s' % str(result))
except Exception as e:
    print('Failed to publish event: %s' % str(e))



