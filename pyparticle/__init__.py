import requests
import base64
import json
import datetime as dt

PARTICLE_API_URL = 'https://api.particle.io'

AUTH_TOKEN_URL = PARTICLE_API_URL + '/oauth/token'
LIST_TOKENS_URL = PARTICLE_API_URL + '/v1/access_tokens' # Unimplemented
DEVICES_URL = PARTICLE_API_URL + '/v1/devices'


INVALID_DETAILS_MESSAGE = 'User credentials are invalid'

class Particle():

    # Initialise the  object used to interact with Particle Cloud API
    #
    # If login details are provided a new access token will be generated other the token given will be used.
    # The provided token is not checked for validity
    def __init__(self, username=None, password=None, access_token=None):

        if username is not None and password is not None:
            self.username = username
            self.password = password

            headers = {'Authorization': 'Basic %s' % base64.encodestring('particle:particle').replace('\n', '')}

            data = {
                'grant_type': 'password',
                'username': self.username,
                'password': self.password
            }

            try:
                response_obj = self.api('POST', AUTH_TOKEN_URL, data=data, headers=headers)
            except:
                raise

            self.access_token = response_obj['access_token']
            self.access_token_expiry_date = dt.datetime.now() + dt.timedelta(seconds=response_obj['expires_in'])
            self.refresh_token = response_obj['refresh_token']

        elif access_token is not None:
            self.access_token = access_token
        else:
            raise ValueError("Username and password or access token must be supplied.")


    # Generic function to handle Particle Cloud API calls
    def api(self, method, url, data={}, params={}, headers={}):

        if method.upper() == 'GET':
            params_str = '&'.join(['%s=%s' % (k, v) for k, v in params.items()])

            response = requests.get(url + '?' + params_str)
        elif method.upper() == 'POST':
            if params:
                params_str = '&'.join(['%s=%s' % (k, v) for k, v in params.items()])
                response = requests.post(url + '?' + params_str, data=data, headers=headers)
            else:
                response = requests.post(url, data=data, headers=headers)

        response_obj = json.loads(response.text)

        if response.status_code != 200:
            if 'error_description' in response_obj:
                if response_obj['error_description'] == INVALID_DETAILS_MESSAGE:
                    raise LoginError()
                else:
                    raise Exception(response_obj['error_description'])

            if 'error' in response_obj:
                raise Exception(response_obj['error'])
            
            # If we still don't have an error message, include the response text
            raise Exception('API Error (Status %d): %s' % (response.status_code, response.text))

        return response_obj

    # List devices that the currently authenticated user has access to.
    #
    # Returns a dict containing the response: https://docs.particle.io/reference/api/#list-devices
    def list_devices(self):

        try:
            devices_obj = self.api('GET', DEVICES_URL, params={'access_token': self.access_token})
        except:
            raise

        return devices_obj


    # Get the current value of a variable exposed by a device.
    #
    # Returns a dict containing the response: https://docs.particle.io/reference/api/#get-a-variable-value
    def get_variable(self, device_id, variable_name):
        url = ''.join([DEVICES_URL, '/', device_id, '/', variable_name])

        try:
            variable_obj = self.api('GET', url, params={'access_token': self.access_token})
        except:
            raise

        return variable_obj

    # Call a function exposed by a device.
    #
    # Returns a dict containing the response: https://docs.particle.io/reference/api/#call-a-function
    def call_function(self, device_id, function_name, arg, raw=False):
        url = ''.join([DEVICES_URL, '/', device_id, '/', function_name])

        try:
            if raw:
                return_value_obj = self.api('POST', url, data={'arg': arg,' format': 'raw', 'access_token': self.access_token})
            else:
                return_value_obj = self.api('POST', url, data={'arg': arg, 'access_token': self.access_token})
        except:
            # TODO: Handle "Failed with Function ... not found" error
            raise

        return return_value_obj['return_value']

    # Publish an event to the Particle Cloud.
    #
    # Args:
    #   event_name: The name of the event to publish
    #   data: Optional data to include with the event (string, max 255 chars)
    #   is_private: Whether the event is private (default: True)
    #
    # Returns a dict containing the response: https://docs.particle.io/reference/api/#publish-an-event
    def publish_event(self, event_name, data='', is_private=True):
        url = ''.join([PARTICLE_API_URL, '/v1/devices/events'])

        event_params = {
            'name': event_name,
            'access_token': self.access_token
        }

        if data:
            event_params['data'] = data

        if is_private:
            event_params['private'] = 'true'
        else:
            event_params['private'] = 'false'

        try:
            response_obj = self.api('POST', url, data=event_params)
        except:
            raise

        return response_obj

class LoginError(Exception):

    def __init__(self):
        super(Exception, self).__init__(INVALID_DETAILS_MESSAGE)
