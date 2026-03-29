import pytest
from app.services.passgen import generate_password

def test_generate_password_default_length():
    password = generate_password()
    assert len(password) == 12

def test_generate_password_custom_length():
    password = generate_password(length=20)
    assert len(password) == 20

def test_generate_password_min_length():
    password = generate_password(length=1)
    assert len(password) == 1

def test_generate_password_invalid_length():
    with pytest.raises(ValueError, match="Password length must be at least 1."):
        generate_password(length=0)
    with pytest.raises(ValueError, match="Password length must be at least 1."):
        generate_password(length=-5)

def test_generate_password_character_set_composition():
    password = generate_password(length=50) # Generate a longer password to increase chances of diverse characters
    assert any(c.islower() for c in password)
    assert any(c.isupper() for c in password)
    assert any(c.isdigit() for c in password)
    assert any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?/~`"\'' for c in password) # Check for common punctuation

def test_generate_password_different_passwords_on_consecutive_calls():
    password1 = generate_password()
    password2 = generate_password()
    assert password1 != password2

def test_generate_password_contains_only_allowed_characters():
    password = generate_password(length=100)
    allowed_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()_+-=[]{}|;:,.<>?/~`\''"
    for char in password:
        assert char in allowed_chars
