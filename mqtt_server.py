import os
import sys
import logging
import time
import argparse
import paho.mqtt.client as mqtt

# Ensure the project root is in the path so we can import parser and database
sys.path.insert(0, os.path.dirname(__file__))

from database import db
from parser import parse_log
import config

logger = logging.getLogger("mqtt_server")

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        logger.info(f"Connected to MQTT broker. Subscribing to topic: {userdata['topic']}")
        client.subscribe(userdata["topic"])
    else:
        logger.error(f"Failed to connect to MQTT broker. Code: {reason_code}")

def on_message(client, userdata, msg):
    """
    Callback when a message is received from the broker.
    We assume the topic is in the format: fab/tool_logs/<tool_id>
    """
    topic = msg.topic
    payload = msg.payload
    
    # Extract tool_id from topic if possible
    parts = topic.split("/")
    tool_id = parts[-1] if len(parts) >= 3 else "MQTT_UNKNOWN"
    
    # We pass a synthetic filename so the parser knows it came from MQTT
    # Since the client sends JSON payloads, use .json extension
    synthetic_filename = f"mqtt_{tool_id}.json"
    
    logger.debug(f"Received message on {topic} ({len(payload)} bytes)")
    
    try:
        entries, warnings = parse_log(payload, synthetic_filename)
        
        # Override tool_id if the parser defaulted to the filename or UNKNOWN
        for entry in entries:
            if entry.tool_id in ("UNKNOWN", "UNKNOWN_TOOL", synthetic_filename, synthetic_filename.replace(".log", "")):
                entry.tool_id = tool_id
                
        if entries:
            n = db.insert_entries(entries)
            logger.info(f"Parsed and inserted {n} records from {topic}")
        else:
            logger.warning(f"No records extracted from payload on {topic}")
            
        for w in warnings:
            logger.warning(f"Parser warning: {w}")
            
    except Exception as e:
        logger.error(f"Error processing message from {topic}: {e}")

def main():
    parser = argparse.ArgumentParser(description="MQTT Server for Smart Log Parser")
    parser.add_argument("--broker", default=config.MQTT_BROKER, help="MQTT Broker IP/Hostname")
    parser.add_argument("--port", type=int, default=config.MQTT_PORT, help="MQTT Broker Port")
    parser.add_argument("--topic", default=f"{config.MQTT_TOPIC_PREFIX}/#", help="Topic to subscribe to")
    args = parser.parse_args()

    # Initialize database
    db.init_db()
    logger.info("Database initialized.")

    # Setup MQTT Client (using v2 protocol API)
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, userdata={"topic": args.topic})
    client.on_connect = on_connect
    client.on_message = on_message

    logger.info(f"Connecting to MQTT broker at {args.broker}:{args.port}...")
    try:
        client.connect(args.broker, args.port, 60)
    except Exception as e:
        logger.error(f"Could not connect to broker: {e}")
        sys.exit(1)

    # Blocking call that processes network traffic, dispatches callbacks
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down MQTT server.")
        client.disconnect()

if __name__ == "__main__":
    main()
