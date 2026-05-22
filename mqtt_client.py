import os
import sys
import time
import json
import random
import datetime
import argparse
import paho.mqtt.client as mqtt

# Try to import config and the synthetic generator
try:
    sys.path.insert(0, os.path.dirname(__file__))
    import config
    from synthetic.generator import _random_entry
    DEFAULT_BROKER = config.MQTT_BROKER
    DEFAULT_PORT = config.MQTT_PORT
    DEFAULT_PREFIX = config.MQTT_TOPIC_PREFIX
except ImportError:
    # If config.py is not present (e.g., running isolated on the Pi),
    # try to load the .env file directly.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass # python-dotenv not installed on the Pi

    DEFAULT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
    DEFAULT_PORT = int(os.environ.get("MQTT_PORT", 1883))
    DEFAULT_PREFIX = os.environ.get("MQTT_TOPIC_PREFIX", "fab/tool_logs")
    
    # Minimal fallback generator if synthetic module is missing
    def _random_entry(base_ts, offset):
        return {
            "timestamp": (base_ts + datetime.timedelta(seconds=offset)).isoformat(),
            "tool_id": "UNKNOWN",
            "severity": "INFO",
            "event_name": "Fallback event",
            "raw_message": "Synthetic generator missing. Falling back."
        }

def main():
    parser = argparse.ArgumentParser(description="MQTT Fab Machine Simulator")
    parser.add_argument("--tool", default="ETCH-01", help="Tool ID (e.g., ETCH-01)")
    parser.add_argument("--broker", default=DEFAULT_BROKER, help="MQTT Broker IP/Hostname")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="MQTT Broker Port")
    parser.add_argument("--topic-prefix", default=DEFAULT_PREFIX, help="Prefix for the MQTT topic")
    parser.add_argument("--interval", type=float, default=1.0, help="Average seconds between logs")
    args = parser.parse_args()

    # Setup MQTT Client
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    
    print(f"Connecting to MQTT broker at {args.broker}:{args.port}...")
    try:
        client.connect(args.broker, args.port, 60)
    except Exception as e:
        print(f"Could not connect to broker: {e}")
        sys.exit(1)

    client.loop_start()

    topic = f"{args.topic_prefix}/{args.tool}"
    print(f"Successfully connected.")
    print(f"Simulating fab machine '{args.tool}'. Publishing to topic '{topic}'...")

    try:
        base_time = datetime.datetime.now()
        offset = 0
        
        while True:
            # Generate a realistic log entry
            entry = _random_entry(base_time, offset)
            entry["tool_id"] = args.tool # Override tool ID to match our cli arg
            
            # Use JSON as the payload format for our simulated machine
            payload = json.dumps(entry)
            
            print(f"Publishing: {payload}")
            client.publish(topic, payload, qos=1)
            
            # Sleep for a random interval to simulate real machine behavior
            sleep_time = random.uniform(args.interval * 0.5, args.interval * 1.5)
            time.sleep(sleep_time)
            
            offset += int(sleep_time)
                
    except KeyboardInterrupt:
        print("\nStopping MQTT client simulator.")
    finally:
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    main()
