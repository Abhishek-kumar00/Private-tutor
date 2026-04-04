import requests
import json

try:
    response = requests.post(
        "http://127.0.0.1:8000/generate-lesson",
        json={"topic": "Solar System"}
    )
    print(f"Status Code: {response.status_code}")
    print("Response Body:")
    # Pretty print the JSON
    import json
    data = response.json()
    print(json.dumps(data, indent=2))
except Exception as e:
    print(f"Error: {e}")
