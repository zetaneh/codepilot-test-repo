import random
import string

def generate_password(length: int = 12) -> str:
    if length < 1:
        raise ValueError("Password length must be at least 1.")

    characters = string.ascii_letters + string.digits + string.punctuation
    password = ''.join(random.choice(characters) for i in range(length))
    return password
