import asyncio
from uvicorn import Config, Server
import threading
import time
import requests

from main import app

def run_server():
    config = Config(app=app, host="127.0.0.1", port=8001, log_level="info")
    server = Server(config=config)
    server.run()

# Run the server in a separate thread
thread = threading.Thread(target=run_server, daemon=True)
thread.start()

# Wait for server to start
time.sleep(3)

# Make a request
try:
    print("Making request...")
    response = requests.post(
        "http://127.0.0.1:8001/generate-lesson",
        json={"topic": "Black Holes"}
    )
    print("Status Code:", response.status_code)
    try:
        print("Response JSON:", response.json())
    except:
        print("Response Text:", response.text)
except Exception as e:
    print("Error:", e)
