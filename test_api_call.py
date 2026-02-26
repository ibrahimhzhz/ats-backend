"""Test what the API returns for job 14 applicants."""
import requests
import json

# First login to get token
login_response = requests.post(
    "http://localhost:8001/auth/login",
    data={
        "username": "test@acme.com",
        "password": "password123"
    }
)

if login_response.status_code != 200:
    print(f"Login failed: {login_response.status_code}")
    print(login_response.text)
    exit()

token = login_response.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# Get applicants for job 14
response = requests.get(
    "http://localhost:8001/applicants/?job_id=14",
    headers=headers
)

print(f"Status: {response.status_code}")
print(f"\nResponse Headers: {dict(response.headers)}")
print(f"\nResponse Body:")
print(json.dumps(response.json(), indent=2))
