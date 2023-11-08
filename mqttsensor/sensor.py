import logging
from pyStib import BASE_URL, LOGGER, StibData 
import yaml
import random
import asyncio
import json
import pytz
import pygtfs
import os
from sqlalchemy.sql import text
from datetime import datetime, timedelta
import requests

LOGGER = logging.getLogger(__name__)
with open('config.yaml', 'r') as file:
    configuration = yaml.safe_load(file)


STIB_API = "https://stibmivb.opendatasoft.com/api/explore/v2.1/catalog/datasets"
STIB_API_KEY = configuration['stib_api_key']
LANG = configuration['lang']
MESSAGE_LANG = configuration['message_lang']
STOP_NAMES = configuration['stop_names']


mqtt_server = configuration['mqtt_server']
mqtt_port = configuration['mqtt_port']
mqtt_user = configuration['mqtt_user']
mqtt_password = configuration['mqtt_password']
TOPIC = "homeassistant/sensor/" 
client_id = f'stib-mqtt-{random.randint(0, 1000)}'

STIB = StibData(STIB_API_KEY)
STIB_LINES = []
STIB_STOP_IDS = []

def diff_in_minutes(t):
    now = pytz.utc.normalize(pytz.utc.localize(datetime.datetime.utcnow()))
    iso = datetime.fromisoformat(t)
    tmp = pytz.utc.normalize(iso)
    return round( (tmp-now).total_seconds()/60)
def dowload_gtfs_files(gtfs_files):
    os.makedirs("gtfs", exist_ok=True)
    for files in gtfs_files:
        response = requests.get(files['url'])
        with open('gtfs/' + files["filename"], mode="wb") as file:
            file.write(response.content)

def import_gtfs_files():
    data = "gtfs"
    (gtfs_root, _) = os.path.splitext(data)
    sqlite_file = f"gtfs.sqlite?check_same_thread=False"
    joined_path = os.path.join("gtfs", sqlite_file)
    gtfs = pygtfs.Schedule(joined_path)
    if not gtfs.feeds:
        pygtfs.append_feed(gtfs, os.path.join(".", data))
    return gtfs

def getGTFSAttributes():
    types = ["Tram", "Train", "Metro", "Bus"]
    dir = ["Suburb", "City"]
    pygtfs = import_gtfs_files()
    now = datetime.now()
    tomorrow = now + timedelta(1)
    yesterday = now - timedelta(1)
    now_date = now.strftime("%Y-%m-%d")
    start_station_id = "5152"
    end_station_id = "5152"
    limit = 24 * 60 * 60 * 2
    limit = int(limit / 2 * 3)
    tomorrow_name = tomorrow.strftime("%A").lower()
    tomorrow_select = f"calendar.{tomorrow_name} AS tomorrow,"
    tomorrow_where = f"OR calendar.{tomorrow_name} = 1"
    tomorrow_order = f"calendar.{tomorrow_name} DESC,"
    where_stop_names = " OR ".join(' stop_name like "' + item + '"' for item in STOP_NAMES)
    print(where_stop_names)

    sql_query = f"""
                 SELECT DISTINCT trips.route_id, trips.direction_id,
                                 stops.stop_id, stops.stop_name, stop_lat, stop_lon, 
                                 route_long_name, route_short_name, route_type,
                                 route_color, route_text_color
                 FROM trips
                 INNER JOIN stop_times
                 ON stop_times.trip_id = trips.trip_id
                 INNER JOIN stops
                 ON stops.stop_id = stop_times.stop_id
                 INNER JOIN routes
                 ON routes.route_id = trips.route_id
                 WHERE {where_stop_names}
                 ORDER BY stops.stop_name, stops.stop_id, route_short_name;
                """
    result = pygtfs.engine.connect().execute(
        text(sql_query)
    )
    print(sql_query)
    """
        {'route_id': '42', 'direction_id': 1, 'trip_headsign': 'GARE DU MIDI', 
        'stop_id': '1414', 'stop_name': 'FOREST CENTRE', 'stop_lat': 50.812012, 
        'stop_lon': 4.318754, 'route_long_name': 'GARE DU MIDI - LOT STATION', 
        'route_short_name': '50', 'route_type': 3, 'route_color': 'B4BD10', 'route_text_color': '000000'}
        STIB FOREST CENTRE - BUS 50 - GARE DU MIDI
    """
    attributes = {}
    for row_cursor in result:
        row = row_cursor._asdict()
        row["route_type"] = types[row['route_type']].upper()
        rln = row["route_long_name"].split(" - ")
        route_long_name = [rln[1], rln[0]]
        destination = route_long_name[row['direction_id']]
        name = f'STIB {row["stop_name"]} - {row["route_type"]} {row["route_short_name"]} - {destination}'
        row["direction_id"] = dir[row['direction_id']].upper()
        attributes[name] = row
        if row['stop_id'] not in STIB_STOP_IDS:
            STIB_STOP_IDS.append(row['stop_id'])
        if row['route_short_name'] not in STIB_LINES:
            STIB_STOP_IDS.append(row['route_short_name'])
    return attributes

def init():
    attributes = getGTFSAttributes()
    #stop_ids = asyncio.run(STIB.get_stopIds(STOP_NAMES))
    #lines_by_stops = asyncio.run(STIB.get_lines_by_stops(stop_ids['stop_ids']))
    #routes = asyncio.run(STIB.get_routes_by_lines(lines_by_stops['lines']))
    passing_times = asyncio.run(STIB.get_passing_times(STIB_STOP_IDS))
    #print(json.dumps(passing_times))
    gtfs_files = asyncio.run(STIB.get_gtfs_files())
    #dowload_gtfs_files(gtfs_files)
    waiting_times = passing_times["waiting_times"]
    for idx, attribute in attributes.items():
        pointid = ''.join(i for i in str(attribute["stop_id"]) if i.isdigit()) 
        lineid = attribute["route_short_name"]
        attribute["passing_time"] = ""
        attribute["destination"] = ""
        attribute["message"] = ""
        attribute["next_passing_time"] = ""
        attribute["next_destination"] = ""
        attribute["next_message"] = ""
        if str(pointid) in waiting_times:
            if str(lineid) in waiting_times[pointid]:
                #print(json.dumps(waiting_times[pointid][lineid]["passingtimes"]))
                if len(waiting_times[pointid][lineid]["passingtimes"]) == 2:
                    wt = waiting_times[pointid][lineid]["passingtimes"]
                    if "expectedArrivalTime" in wt[0]:
                        attribute["passing_time"] = wt[0]["expectedArrivalTime"]
                    if "destination" in wt[0]:
                        attribute["destination"] =  wt[0]["destination"][LANG]
                    if "message" in wt[0]:
                        attribute["message"] =  wt[0]["message"][MESSAGE_LANG]
                    if "expectedArrivalTime" in wt[1]:
                        attribute["next_passing_time"] = wt[1]["expectedArrivalTime"]
                    if "destination" in wt[1]:
                        attribute["next_destination"] = wt[1]["destination"][LANG]
                    if "message" in wt[1]:
                        attribute["next_message"] = wt[1]["message"][MESSAGE_LANG]
                if len(waiting_times[pointid][lineid]["passingtimes"]) == 1:
                    wt = waiting_times[pointid][lineid]["passingtimes"]
                    if "expectedArrivalTime" in wt[0]:
                        attribute["passing_time"] = wt[0]["expectedArrivalTime"]
                    if "destination" in wt[0]:
                        attribute["destination"] =  wt[0]["destination"][LANG]
                    if "message" in wt[0]:
                        attribute["message"] =  wt[0]["message"][MESSAGE_LANG]
            else:
                print(f'no {lineid} in {pointid}  {attribute["stop_name"]}')
        else:
            print(f'no {pointid} in waitingtimes {attribute["stop_name"]}')


        
    print(json.dumps(attributes))
        
    """
    for idx, line_details in lines_by_stops['line_details'].items():
        for l in line_details:
            line_id = str(l["line_id"])
            for point in l["points"]:
                p = str(''.join(i for i in str(point["id"]) if i.isdigit()))
                if p in stop_ids["stop_fields"]:
                    if "lines" not in stop_ids["stop_fields"][p]:
                        stop_ids["stop_fields"][p].update({"lines" : [line_id]})
                    else:
                        stop_ids["stop_fields"][p]["lines"].append(line_id)

                    if "line_details" not in stop_ids["stop_fields"][p]:
                        stop_ids["stop_fields"][p].update({"line_details" : {line_id : l}})
                    else:
                        if line_id not in stop_ids["stop_fields"][p]["line_details"]:
                            stop_ids["stop_fields"][p]["line_details"][line_id] = l 
                        else:
                            stop_ids["stop_fields"][p]["line_details"][line_id].update(l)
                    if line_id in routes:
                        stop_ids["stop_fields"][p]["line_details"][line_id].update(routes[line_id])
                    if p in waiting_times:
                        if line_id in waiting_times[p]:
                            stop_ids["stop_fields"][p]["line_details"][line_id].update(waiting_times[p][line_id])
    #print(json.dumps(stop_ids))
    """
    pass

def mq_config():
    client = connect_mqtt()
    client.loop_start()
    publish(client)

if __name__ == "__main__":
    init()
   # mq_config()
