#!/usr/bin/env python3
"""Test script to verify OpenAI API configuration"""

import os
from openai import OpenAI

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

def test_openai_connection():
    """Test OpenAI API connection with configured credentials"""
    try:
        # Get configuration from environment
        api_key = os.getenv('OPENAI_API_KEY')
        base_url = os.getenv('OPENAI_API_BASE_URL')
        
        print(f"🔧 Testing OpenAI API Configuration")
        print(f"📍 Base URL: {base_url}")
        print(f"🔑 API Key: {'sk-proj-...' + api_key[-10:] if api_key else 'Not found'}")
        
        if not api_key:
            print("❌ No OpenAI API key found in environment")
            return False
        
        # Initialize OpenAI client
        client = OpenAI(
            api_key=api_key,
            base_url=base_url if base_url else None
        )
        
        # Test with a simple completion
        print("\n🧪 Testing API call...")
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Say hello and confirm you're working!"}
            ],
            max_tokens=100
        )
        
        print("✅ API Test Successful!")
        print(f"📝 Response: {response.choices[0].message.content}")
        return True
        
    except Exception as e:
        print(f"❌ API Test Failed: {str(e)}")
        return False

if __name__ == "__main__":
    success = test_openai_connection()
    if success:
        print("\n🎉 OpenAI configuration is working correctly!")
        print("✨ Your Open WebUI project is properly configured to use OpenAI.")
    else:
        print("\n⚠️  OpenAI configuration needs attention.")