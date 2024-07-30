from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

def encrypt_password(password: str) -> str:
    if not password:
        return ''
    f = Fernet(current_app.config['ENCRYPTION_KEY'])
    encrypted_password = f.encrypt(password.encode())
    return encrypted_password.decode()

def decrypt_password(encrypted_password: str) -> str:
    if not encrypted_password:
        return ''
    f = Fernet(current_app.config['ENCRYPTION_KEY'])
    try:
        decrypted_password = f.decrypt(encrypted_password.encode())
        return decrypted_password.decode()
    except InvalidToken:
        return ''