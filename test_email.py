import requests

url = "http://localhost:3000/send-email"

payload = {
    "email_type": "SIGNUP_WELCOME",
    "recipient_email": "iamsurya788@gmail.com",  # Using your actual email!
    "details": {
        "name": "Suryaprakash"
    }
}

print("Sending request to Microservice...")
response = requests.post(url, json=payload)

print(f"Status Code: {response.status_code}")
print(f"Response: {response.text}")