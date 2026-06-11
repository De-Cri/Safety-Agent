import os
from fastapi import Header, HTTPException, status


async def require_api_key(x_api_key: str = Header(...)):
    if x_api_key != os.environ["API_KEY"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
