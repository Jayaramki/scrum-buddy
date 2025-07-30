#!/usr/bin/env python3
"""
Utility script to generate bcrypt password hashes for Scrum Buddy authentication.

Usage:
    python generate_password_hash.py

This script will prompt you for a password and generate a bcrypt hash
that you can use in your environment variables.
"""

import bcrypt
import getpass

def generate_hash(password: str) -> str:
    """Generate a bcrypt hash for the given password"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def main():
    print("🔐 Scrum Buddy Password Hash Generator")
    print("=" * 40)
    
    while True:
        # Get password from user (hidden input)
        password = getpass.getpass("Enter password to hash: ")
        
        if not password:
            print("❌ Password cannot be empty!")
            continue
        
        # Generate hash
        password_hash = generate_hash(password)
        
        print(f"\n✅ Generated hash:")
        print(f"   {password_hash}")
        
        # Show example usage
        username = input("\nEnter username for this password (optional): ").strip()
        if username:
            env_var = f"AUTH_USER_{username.upper()}"
            print(f"\n📋 Add this to your .env file:")
            print(f"   {env_var}={password_hash}")
        
        # Ask if user wants to generate another
        another = input("\nGenerate another hash? (y/N): ").strip().lower()
        if another not in ['y', 'yes']:
            break
    
    print("\n👋 Done! Remember to add the generated hashes to your .env file.")

if __name__ == "__main__":
    main()