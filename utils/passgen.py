import random
import string

def generate_password(length: int) -> str:
    """
    Generates a random password of a specified length using a mix of character types.

    Args:
        length: The desired length of the password.

    Returns:
        A randomly generated password.

    Raises:
        ValueError: If the length is less than 1.
    """
    if length < 1:
        raise ValueError("Password length must be at least 1.")

    characters = string.ascii_letters + string.digits + string.punctuation
    password = ''.join(random.choices(characters, k=length))
    return password

if __name__ == "__main__":
    # Demonstrate the password generation
    try:
        print("Generating a 12-character password:")
        sample_password = generate_password(12)
        print(f"Generated password: {sample_password}")

        print("\nGenerating a 8-character password:")
        sample_password_short = generate_password(8)
        print(f"Generated password: {sample_password_short}")

        print("\nAttempting to generate a 0-character password (should raise ValueError):")
        generate_password(0)
    except ValueError as e:
        print(f"Error: {e}")
