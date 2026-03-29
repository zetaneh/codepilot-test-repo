from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    # This is a mock implementation for testing purposes.
    # In a real application, you would decode the token and fetch the user from a database.
    if token == "mock_token_alice":
        return User(id=1, name="Alice", email="alice@example.com", is_active=True)
    elif token == "mock_token_bob":
        return User(id=2, name="Bob", email="bob@example.com", is_active=True)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")
    return current_user
