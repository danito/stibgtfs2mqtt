import json
import asyncio
import async_timeout
import aiohttp
from datetime import datetime
import pytz
import datetime
import logging

LOGGER = logging.getLogger(__name__)
BASE_URL = "https://stibmivb.opendatasoft.com/api/explore/v2.1/catalog/datasets"

class StibData:
    """A class to get passage information."""

    def __init__(self, api_key, session=None):
        """Initialize the class."""
        self.session = session
        self.api_key = api_key
        self.stib_api = STIBApi()
        self.stop_ids= []
        self.stop_fields = {}
        self.state = {}
        self.config = {}
        self.attributes = {}

    async def get_stopIds(self, stopnames):
        """Get the stop ids from the stop name."""
        stop_names = []
        for stop, stop_name in enumerate(stopnames):
               stop_names.append(stop_name.upper())
        q = " OR ".join(f' name ="{item.upper()}"' for item in stop_names)
        dataset='stop-details-production'
        stop_data = await self.stib_api.get_stib_data(dataset, q, self.api_key)
        if stop_data is not None and 'results' in stop_data:
            for r in stop_data['results']:
                stop_id = str(r['id'])
                stop_id_num = str(''.join(i for i in str(stop_id) if i.isdigit()))        
                stop_name = json.loads(r["name"])
                stop_gps  = json.loads(r['gpscoordinates'])
                self.stop_ids.append(stop_id)
                self.stop_fields[stop_id_num] = {"stop_id" : stop_id, "stop_names" : stop_name, "gps_coordinates" : stop_gps }
        return {"stop_ids" : self.stop_ids, "stop_fields" : self.stop_fields}
    
    async def get_gtfs_stops(self, stopnames):
        """Get the stop ids from the stop name."""
        stop_names = []
        stop_ids = []
        stop_fields = {}
        for stop, stop_name in enumerate(stopnames):
               stop_names.append(stop_name.upper())
        q = " OR ".join(f' stop_name = "{item.upper()}" ' for item in stop_names)
        dataset='gtfs-stops-production'
        stop_data = await self.stib_api.get_stib_data(dataset, q, self.api_key)
        if stop_data is not None and 'results' in stop_data:
            for r in stop_data['results']:
                stop_id = str(r['stop_id'])
                stop_id_num = str(''.join(i for i in str(stop_id) if i.isdigit()))        
                stop_name = r["stop_name"]
                stop_gps  = r['stop_coordinates']
                stop_ids.append(stop_id)
                stop_fields[stop_id_num] = {"stop_id" : stop_id, "stop_name" : stop_name, "stop_coordinates" : stop_gps }
        return {"stop_ids" : stop_ids, "stop_fields" : stop_fields}
    
    async def get_passing_times(self, stop_ids):
        """Get the stop ids from the stop name."""
        """ delete letters from stop is"""
        q = " OR ".join('pointid like "' + ''.join(i for i in str(item) if i.isdigit()) + '"' for item in stop_ids)
        dataset='waiting-time-rt-production'
        stib_data = await self.stib_api.get_stib_data(dataset, q, self.api_key)
        line_ids = []
        waiting_times = {}
        if stib_data is not None and 'results' in stib_data:
            for r in stib_data['results']:
                stop_id = str(r["pointid"])
                stop_id_num = str(''.join(i for i in str(stop_id) if i.isdigit()))   
                line_id = str(r["lineid"])
                if line_id not in line_ids:
                    line_ids.append(line_id)
                r["passingtimes"] = json.loads(r["passingtimes"])
                if stop_id_num not in waiting_times:
                    waiting_times[stop_id_num] = {line_id : r}
                else:
                    if line_id not in waiting_times[stop_id_num]:
                        waiting_times[stop_id_num][line_id] = r
                    else:
                        waiting_times[stop_id_num][line_id].update(r)

        return {"line_ids" : line_ids, "waiting_times" : waiting_times}
    
    async def get_lines_by_stops(self, stop_ids):
        """Get line info from the stop ids."""
        q = " OR ".join(' points like "' + item + '"' for item in stop_ids)
        dataset='stops-by-line-production'
        stib_data = await self.stib_api.get_stib_data(dataset, q, self.api_key)
        lines = []
        line_details = {}
        if stib_data is not None and 'results' in stib_data:
            for r in stib_data['results']:
                line_id = str(r['lineid'])
                direction = r['direction']
                destination = json.loads(r['destination'])
                points = json.loads(r['points'])
                ld = {'line_id': line_id, 'direction': direction, 'destination': destination, "points" : points}
                if line_id not in line_details:
                    line_details[line_id] = [ld]
                else:
                    line_details[line_id].append(ld)
                if line_id not in lines:
                    lines.append(line_id)
        return {'lines': lines, 'line_details' : line_details}
    
    async def get_routes_by_lines(self, line_ids):
        """Get the stop ids from the stop name."""
        q = " OR ".join(' route_short_name like "' + item + '"' for item in line_ids)
       
        dataset='gtfs-routes-production'
        stib_data = await self.stib_api.get_stib_data(dataset, q, self.api_key)
        route_details = {}
        if stib_data is not None and 'results' in stib_data:

            for r in stib_data['results']:
                line_id = str(r['route_short_name'])
                route_id = str(r['route_id'])
                route_long_name = r['route_long_name']
                route_type = r['route_type']
                route_color = r['route_color']
                route_details[line_id] = {'route_id': route_id, 'route_short_name': line_id, 'route_long_name' : route_long_name, 'route_type' : route_type, 'route_color' : route_color }
        return route_details
    
    async def get_gtfs_files(self):
        """Get the stop ids from the stop name."""
        dataset='gtfs-files-production'
        stib_data = await self.stib_api.get_stib_data(dataset, "", self.api_key)
        gtfs_files = []
        if stib_data is not None and 'results' in stib_data:
            for r in stib_data['results']:
                url = r["file"]["url"]
                filename = r["file"]["filename"]
                gtfs_files.append({"url" : url, "filename" : filename})
        return gtfs_files
    
class STIBApi:
   
    async def get_stib_data(self, dataset, query, api_key, session=None):
        selfcreatedsession = False
        self.api_key = api_key
        self.session = session
        result = None
        if self.session is None:
            selfcreatedsession = True
        params = dict(
            where=query,
            start=0,
            rows=99,
            apikey = self.api_key
         )
        endpoint = "{}/{}/records".format(
            BASE_URL, dataset
        )
        common = CommonFunctions(self.session)
        result = await common.api_call(endpoint, params)
        if selfcreatedsession is True:
                await common.close()
        return result
            

class CommonFunctions:
    """A class for common functions."""

    def __init__(self, session):
        """Initialize the class."""
        self.session = session

    async def api_call(self, endpoint, params):
        """Call the API."""
        data = None
        if self.session is None:
            self.session = aiohttp.ClientSession()
        try:
            async with async_timeout.timeout(5):
                LOGGER.debug("Endpoint URL: %s", str(endpoint))
                response = await self.session.get(url=endpoint, params=params)
                if response.status == 200:
                    try:
                        data = await response.json()
                    except ValueError as exception:
                        message = "Server gave incorrect data"
                        raise Exception(message) from exception

                elif response.status == 401:
                    message = "401: Acces token might be incorrect"
                    raise HttpException(message, await response.text(), response.status)

                elif response.status == 404:
                    message = "404: incorrect API request"
                    raise HttpException(message, await response.text(), response.status)
                elif response.status == 400:
                    message = "400: incorrect API request"
                    raise HttpException(message, await response.text(), response.status)

                else:
                    message = f"Unexpected status code {response.status}."
                    raise HttpException(message, await response.text(), response.status)

        except aiohttp.ClientError as error:
            LOGGER.error("Error connecting to Stib API: %s", error)
        except asyncio.TimeoutError as error:
            LOGGER.debug("Timeout connecting to Stib API: %s", error)
        return data

    async def close(self):
        """Close the session."""
        await self.session.close()


class HttpException(Exception):
    """HTTP exception class with message text, and status code."""

    def __init__(self, message, text, status_code):
        """Initialize the class."""
        super().__init__(message)
        self.status_code = status_code
        self.text = text
