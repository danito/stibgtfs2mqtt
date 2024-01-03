# stibgtfs2mqtt
get real time data from STIB-MIVB api and offline data from GTFS.
Data is send over MQTT server to Home-Assisant with auto-discover.

# MQTT server settings
Edit config.yaml with your settings for your mqtt broker.

## Info

### example of config.yaml
```yaml
mqtt_server: 'localhost'
mqtt_port: '1883'
mqtt_user: 'username'
mqtt_password: 'password'
mqtt_topic: 'homeassistant/sensor'
stib_api_key: '022efe811eqkqeeoae35fbcca3abc88ah6854e6f418'
lang: 'fr'
message_lang: 'fr'
stop_names:
        - "MAX WALLER"
        - "SAINT-DENIS"
        - "FOREST CENTRE"
clean_on_start: 0
gtfs: false
```
This will publish config, attributes and state to mqtt topic homeassistant/sensor/stibLxxStopIdX/ and will be autodiscovered.
set clean_on_start to 1 if you want to publish empty topic to delete the entities in HA. It sends an empty message to the config topic to clear the entity.
Set gtfs to true if you want to use data from local GTFS files. Pay attention as this will download the gtfs files and will use more the 2.5G of disk space by building a sqlite3 data base.
If it's set to false, we use only the STIB api to get stop, line and route info, but their data is inconsistent and differ with gtfs data. We also don't get data for the Noctis busses.
Therefore name of entities are different for both methods and if you switch from one to another you will get a lot of sensors without updated states. So better do a clear_mqtt before changing. 

##Installation
This is a stand alone python script, not a custom component.
Rename and edit example.config.yaml to config.yaml.
```
pip3 install requirements.txt
```
to install all dependencies.
Run python3 sensor.py to start the script. If you use GTFS, it will take several minutes to download and create the gtfs database.
