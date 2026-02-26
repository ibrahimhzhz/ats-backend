import google.generativeai as genai
import os
from dotenv import load_dotenv

# 1. Load the key
load_dotenv(override=True)
api_key = os.getenv("GEMINI_API_KEY")

print(f"🔑 Key found: {str(api_key)[:10]}...") 

if not api_key:
    print("❌ Error: No API Key found in .env file")
    exit()

# 2. Configure
try:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')

    # 3. Test Call
    print("📡 Connecting to Google...")
    response = model.generate_content("Say 'Hello, your API key is working!' if you can hear me.")

    print("\n✅ SUCCESS! Google replied:")
    print(response.text)

except Exception as e:
    print("\n❌ FAILURE! The key did not work.")
    print(f"Error details: {e}")