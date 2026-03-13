import smtplib

# PUT YOUR EXACT DETAILS HERE
EMAIL = "iamsurya788@gmail.com"
PASSWORD = "pzdbiiyeplsvfvrh"

print("Attempting to connect to Google...")

try:
    # Connect to Google's server
    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.ehlo()
    # Start the mandatory encryption
    server.starttls()
    
    # Try to log in
    server.login(EMAIL, PASSWORD)
    print("✅ SUCCESS! Google accepted your password. The credentials are perfect.")
    server.quit()
    
except smtplib.SMTPAuthenticationError:
    print("❌ FAILED: Google rejected the password. It is either typed wrong or has spaces.")
except Exception as e:
    print(f"❌ FAILED: Another error occurred: {e}")