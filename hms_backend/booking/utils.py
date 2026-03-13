import requests

def trigger_hospital_email(email_type, recipient_email, patient_name):
    """
    Sends a payload to the local Serverless email microservice.
    """
    # Using 127.0.0.1 to avoid that Windows localhost bug from earlier!
    url = "http://localhost:3000/send-email"
    
    payload = {
        "email_type": email_type,
        "recipient_email": recipient_email,
        "details": {
            "name": patient_name
        }
    }
    
    try:
        # We add a 5-second timeout so Django doesn't freeze if the microservice is turned off
        response = requests.post(url, json=payload, timeout=5)
        
        if response.status_code == 200:
            print(f"✅ Django successfully queued {email_type} for {recipient_email}")
            return True
        else:
            print(f"❌ Microservice rejected the request: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Django could not reach the microservice: {e}")
        return False