from cryptography.fernet import Fernet

def generate_key():
    return Fernet.generate_key()

# Generate the key and print it
key = generate_key()
print(key.decode())

# Store this key securely and use it in your configuration only when nessessary

# Iddeally store like this
#export ENCRYPTION_KEY='your_generated_encryption_key'