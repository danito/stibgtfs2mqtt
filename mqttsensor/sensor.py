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
import time
from paho.mqtt import client as mqtt_client

LOGGER = logging.getLogger(__name__)
with open('config.yaml', 'r') as file:
    configuration = yaml.safe_load(file)


STIB_API = "https://stibmivb.opendatasoft.com/api/explore/v2.1/catalog/datasets"
STIB_API_KEY = configuration['stib_api_key']
LANG = configuration['lang']
MESSAGE_LANG = configuration['message_lang']
STOP_NAMES = configuration['stop_names']
CLEAN = False 

mqtt_server = configuration['mqtt_server']
mqtt_port = configuration['mqtt_port']
mqtt_user = configuration['mqtt_user']
mqtt_password = configuration['mqtt_password']
TOPIC = configuration['mqtt_topic']
GTFS = configuration['gtfs']

client_id = f'stib-mqtt-{random.randint(0, 1000)}'

STIB = StibData(STIB_API_KEY)
STIB_LINES = []
STIB_STOP_IDS = []
FIRSTRUN = 0

def diff_in_minutes(t):
    if not t:
        return None
    now = pytz.utc.normalize(pytz.utc.localize(datetime.utcnow()))
    iso = datetime.fromisoformat(t)
    tmp = pytz.utc.normalize(iso)
    return round( (tmp-now).total_seconds()/60)

def download_gtfs_files(gtfs_files):
    os.makedirs("gtfs", exist_ok=True)
    for files in gtfs_files:
        response = requests.get(files['url'])
        with open('gtfs/' + files["filename"], mode="wb") as file:
            file.write(response.content)

def import_gtfs_files():
    print("Checking for gtfs file.")
    data = "gtfs"
    (gtfs_root, _) = os.path.splitext(data)
    #sqlite_file = f"gtfs.sqlite?check_same_thread=False"
    sqlite_file = f"gtfs.sqlite"
    joined_path = os.path.join("gtfs", sqlite_file)
    if not os.path.exists(joined_path):
        print("Downloading files from stib-mivb.be")
        gtfs_files = asyncio.run(STIB.get_gtfs_files())
        download_gtfs_files(gtfs_files)
        t = os.path.join("gtfs","translations.txt")
        if os.path.exists(t):
            os.remove(t)
    gtfs = pygtfs.Schedule(joined_path)
    if not gtfs.feeds:
        pygtfs.append_feed(gtfs, os.path.join(".", data))
    return gtfs

def getGTFSAttributes():
    types = ["Tram", "Train", "Metro", "Bus"]
    dir = ["Suburb", "City"]
    pygtfs = import_gtfs_files()
    print("Retrieving gtfs data for selected STIB-MIVB stations")
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
                 INNER JOIN calendar
                 ON  calendar.service_id = trips.service_id
                 WHERE {where_stop_names}
                 AND start_date <= "{now_date}" 
                 AND end_date >= "{now_date}"
                 ORDER BY stops.stop_name, stops.stop_id, route_short_name;
                """
    result = pygtfs.engine.connect().execute(
        text(sql_query)
    )
    """
        {'route_id': '42', 'direction_id': 1, 'trip_headsign': 'GARE DU MIDI', 
        'stop_id': '1414', 'stop_name': 'FOREST CENTRE', 'stop_lat': 50.812012, 
        'stop_lon': 4.318754, 'route_long_name': 'GARE DU MIDI - LOT STATION', 
        'route_short_name': '50', 'route_type': 3, 'route_color': 'B4BD10', 'route_text_color': '000000'}
        STIB FOREST CENTRE - BUS 50 - GARE DU MIDI
    """
    attributes = {}
    attributes_2 = [] 
    for row_cursor in result:
        row = row_cursor._asdict()
        row['stop_ids'] = []
        row['route_lons'] = []
        row['route_lats'] = []
        row["route_type"] = types[row['route_type']].upper()
        rln = row["route_long_name"].split(" - ")
        route_long_name = [rln[1], rln[0]]
        destination = route_long_name[row['direction_id']]
        name = f'STIB {row["stop_name"]} - {row["route_type"]} {row["route_short_name"]} - {destination}'
        if name in attributes:
            pointid = ''.join(i for i in str(row["stop_id"]) if i.isdigit()) 
            attributes[name]['stop_ids'].append(pointid)
        else:
            pointid = ''.join(i for i in str(row["stop_id"]) if i.isdigit()) 
            row['stop_ids'].append(pointid)
            row["direction_id"] = dir[row['direction_id']].upper()
            attributes[name] = row
        attributes_2.append(row)
        if row['stop_id'] not in STIB_STOP_IDS:
            STIB_STOP_IDS.append(row['stop_id'])
        if row['route_short_name'] not in STIB_LINES:
            STIB_LINES.append(row['route_short_name'])
        with open('attributes_2.json', 'w', encoding='utf-8') as f:
            json.dump(attributes_2, f, ensure_ascii=False, indent=4)
    return attributes

def getSTIBAttributes():
    types = ["Tram", "Train", "Metro", "Bus"]
    row=[]
    stop_ids = asyncio.run(STIB.get_gtfs_stops(STOP_NAMES))
    lines_by_stops = asyncio.run(STIB.get_lines_by_stops(stop_ids['stop_ids']))
    routes = asyncio.run(STIB.get_routes_by_lines(lines_by_stops['lines']))
    attributes = {}
    for idx, rows in lines_by_stops["line_details"].items():
        for row in rows:
            row['stop_ids'] = []
            for point in row['points']:
                if point["id"] in stop_ids["stop_ids"]:
                    stop_id = point["id"]
                    stop_id_num = str(''.join(i for i in str(stop_id) if i.isdigit())) 
                    row["stop_id"] = stop_ids["stop_fields"][stop_id_num]["stop_id"]
                    row["stop_name"] = stop_ids["stop_fields"][stop_id_num]["stop_name"]
                    row["stop_lat"] = stop_ids["stop_fields"][stop_id_num]["stop_coordinates"]["lat"]
                    row["stop_lon"] = stop_ids["stop_fields"][stop_id_num]["stop_coordinates"]["lon"]
            if row["line_id"] in routes:
                row["route_long_name"] = routes[row["line_id"]]["route_long_name"]
                row["route_type"] = routes[row["line_id"]]["route_type"].upper()
                row["route_color"] = routes[row["line_id"]]["route_color"]
                row["route_id"] = routes[row["line_id"]]["route_id"]
                destination = row["destination"][LANG]
            name = f'STIB {row["stop_name"]} - {row["route_type"]} {row["line_id"]} - {destination}'
            row["direction_id"] = row['direction'].upper()
            row["route_short_name"] = row["line_id"]
            row["route_text_color"] = "000000"

            if name in attributes:
                pointid = ''.join(i for i in str(row["stop_id"]) if i.isdigit()) 
                attributes[name]['stop_ids'].append(pointid)
            else:
                pointid = ''.join(i for i in str(row["stop_id"]) if i.isdigit()) 
                row['stop_ids'].append(pointid)
                attributes[name] = row
            if row['stop_id'] not in STIB_STOP_IDS:
                STIB_STOP_IDS.append(row['stop_id'])
            if row['line_id'] not in STIB_LINES:
                STIB_LINES.append(row['line_id'])
    return attributes



def init(clean = False):
    if GTFS:
        attributes = getGTFSAttributes()
    else:
        attributes = getSTIBAttributes()
    print("Retrieving STIB-MIVB realtime data")
    passing_times = asyncio.run(STIB.get_passing_times(STIB_STOP_IDS))
    waiting_times = passing_times["waiting_times"]
    if clean:
        cleanMqtt()
        clean = True;
    for idx, attribute in attributes.items():
        pointids = attribute["stop_ids"]
        lineid = attribute["route_short_name"]
        attribute["name"] = idx
        attribute["passing_time"] = ""
        attribute["destination"] = ""
        attribute["message"] = ""
        attribute["next_passing_time"] = ""
        attribute["next_destination"] = ""
        attribute["next_message"] = ""
        for pointid in pointids:
            if str(pointid) in waiting_times:
                if str(lineid) in waiting_times[pointid]:
                    if len(waiting_times[pointid][lineid]["passingtimes"]) == 2:
                        wt = waiting_times[pointid][lineid]["passingtimes"]
                        if "expectedArrivalTime" in wt[0]:
                            attribute["passing_time"] = wt[0]["expectedArrivalTime"]
                            attribute["stop_id"] = pointid
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
                            attribute["stop_id"] = pointid
                        if "destination" in wt[0]:
                            attribute["destination"] =  wt[0]["destination"][LANG]
                        if "message" in wt[0]:
                            attribute["message"] =  wt[0]["message"][MESSAGE_LANG]
        if FIRSTRUN == 0:
            setConfig(attribute)
        diff = diff_in_minutes(attribute['passing_time'])
        print(f"Sending data for {idx}: {diff}") 
        setAttribute(attribute)
        setState(attribute)
    return

def setState(attribute):
    key = "stib" + attribute["stop_id"] + attribute["route_short_name"] + attribute["direction_id"] 
    state = {
                        "arrival": diff_in_minutes(attribute['passing_time'])
            }
    topic = TOPIC + key + "/state"
    mqttSend(state,topic,False)
    return
    
    
def setAttribute(attribute):
    key = "stib" + attribute["stop_id"] + attribute["route_short_name"] + attribute["direction_id"] 
    a = {                   
                    "route_id": attribute["route_id"],
                    "direction_id": attribute["direction_id"],
                    "stop_id": attribute["stop_id"],
                    "stop_name": attribute["stop_name"],
                    "latitude": attribute["stop_lat"],
                    "longitude": attribute["stop_lon"],
                    "route_long_name": attribute["route_long_name"],
                    "route_short_name": attribute["route_short_name"],
                    "route_type": attribute["route_type"],
                    "route_color": attribute["route_color"],
                    "route_text_color": attribute["route_text_color"],
                    "passing_time": attribute["passing_time"],
                    "destination": attribute["destination"],
                    "message": attribute["message"],
                    "next_passing_time": attribute["next_passing_time"],
                    "next_destination": attribute["next_destination"],
                    "next_message": attribute["next_message"]
    }                        
    topic = TOPIC + key + "/attribute"
    mqttSend(a,topic,False)
    return None
                    
def setConfig(attribute):
    key = "stib" + attribute["stop_id"] + attribute["route_short_name"] + attribute["direction_id"] 
    config = {
                "icon" : "",                        
                "device_class": "duration",
                "json_attributes_template": "{{value_json | default('') | to_json}}",
                "json_attributes_topic": None,
                "state_topic": None,
                "command_topic": None,
                "unique_id": None,
                "unit_of_measurement": 'min',
                "value_template": '{{value_json.arrival}}',
                "device" : {}
            }
    c = config.copy()
    c.update(
        {
            "json_attributes_topic": TOPIC + key + "/attribute",
            "state_topic": TOPIC + key + "/state",
            "command_topic": TOPIC + key + "/set",
            "unique_id": key,
        }
    )
    c.update({
            "icon" : "mdi:" + attribute["route_type"].lower(),
            "device" : {
                "identifiers" : [key],
                "name" : attribute["name"]
            }
            
    })
    topic = TOPIC + key + "/config"
    mqttSend(c,topic,True)
    return 
def cleanMqtt():
    client = connect_mqtt()
    for stop in STIB_STOP_IDS:
        for line in STIB_LINES:
            key = "stib"+stop+line+"CITY"
            topic = TOPIC+key+"/config"
            client.publish(topic)
            key = "stib"+stop+line+"SUBURB"
            topic = TOPIC+key+"/config"
            client.publish(topic)
    quit()

def connect_mqtt():
    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            print("Connected to MQTT Broker!")
        else:
            print("Failed to connect, return code %d\n", rc)
    # Set Connecting Client ID
    client = mqtt_client.Client(client_id)
    client.username_pw_set(mqtt_user, mqtt_password)
    client.on_connect = on_connect
    client.connect(mqtt_server, int(mqtt_port))
    return client

def mqttSend(msg,topic,retain = False):
    client = connect_mqtt()
    #client.loop_start()
    msg = json.dumps(msg, indent=4, sort_keys=True, ensure_ascii=False)
    response = client.publish(topic, msg, qos=0, retain=retain)
    status = response[0]
    if status != 0:
        print(f"Failed to send message to topic {topic}")
    return

def mq_config():
    client = connect_mqtt()
    client.loop_start()
    publish(client)

if __name__ == "__main__":
    while True:
        clean = False
        if CLEAN :
            clean = True
        init(clean)
        clean = False
        FIRSTRUN = FIRSTRUN + 1
        print(FIRSTRUN)
        time.sleep(30)
