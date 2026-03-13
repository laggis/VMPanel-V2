import uvicorn

if __name__ == "__main__":
    # Port 8000 is often occupied by system services on Windows.
    # Changed to 8081 to avoid WinError 10013.
    # Disable reload for stability in production-like testing
    # Port 8081 seems stuck, trying 8083
    uvicorn.run("app.main:app", host="0.0.0.0", port=8082, reload=False, log_level="debug")
