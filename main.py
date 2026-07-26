from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from routes import auth, listings, search, users, recommendations, messages
from routes import dob
#from routes import whatsapp_webhook

load_dotenv()

app = FastAPI(
    title   = "Damundjé API",
    version = "0.4.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

app.include_router(auth.router,             prefix="/api/auth",            tags=["Auth"])
app.include_router(listings.router,         prefix="/api/listings",        tags=["Listings"])
app.include_router(search.router,           prefix="/api/search",          tags=["Search"])
app.include_router(users.router,            prefix="/api/users",           tags=["Users"])
app.include_router(recommendations.router,  prefix="/api/recommendations", tags=["ML"])
app.include_router(messages.router,         prefix="/api/conversations",   tags=["Chat"])
app.include_router(dob.router,              prefix="/api/dob",             tags=["DOB"])
#app.include_router(whatsapp_webhook.router, prefix="/api/whatsapp",        tags=["WhatsApp"])

@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "app": "Damundjé API 🛒", "version": "0.4.0"}
