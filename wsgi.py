import os
from app import app, init_db

# Initialize DB on first import (tables created if missing)
init_db()

application = app  # PythonAnywhere expects `application`