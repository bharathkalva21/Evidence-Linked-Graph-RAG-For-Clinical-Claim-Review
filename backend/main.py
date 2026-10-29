from fastapi import FastAPI
from backend.api.routes import router

app = FastAPI(
    title="Multi-Agent Graph-RAG CDSS",
    description="Research prototype backend for clinical decision support",
    version="0.1.0"
)

from fastapi.staticfiles import StaticFiles


class FreshFrontendFiles(StaticFiles):
    """Avoid mixing a cached UI script with newly deployed report markup."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response


app.include_router(router)

# Mount the frontend UI
app.mount("/ui", FreshFrontendFiles(directory="frontend", html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
