# Deploy on PythonAnywhere (Free Tier)

## What you need
- A free account at pythonanywhere.com
- The files in this folder (app.py, wsgi.py, graders, templates/, requirements.txt)

## Steps

### 1. Upload files
- Log in to PythonAnywhere
- Go to the **Files** tab
- Create a folder: `submission-portal`
- Upload ALL files from this folder into `submission-portal/`
  (app.py, wsgi.py, code_grader.py, dwg_grader.py, pdf_grader.py,
   requirements.txt, .env.example, and the templates/ folder)
- Make sure templates/ keeps its folder structure

### 2. Create a virtual environment + install deps
- Open a **Bash console** (Consoles tab)
- Run:
```
cd ~/submission-portal
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Create the web app
- Go to the **Web** tab
- Click **Add a new web app** -> **Manual configuration** -> **Python 3.10**
- Set **Source code**: `/home/<your-username>/submission-portal`
- Set **Working directory**: `/home/<your-username>/submission-portal`

### 4. Configure WSGI
- In the Web tab, click the **WSGI configuration file** link
- Replace ALL content with:
```python
import sys
sys.path.insert(0, '/home/<your-username>/submission-portal')

from wsgi import application
```
- Replace `<your-username>` with your actual PythonAnywhere username

### 5. Set the virtual environment
- In the Web tab, set **Virtualenv** to:
`/home/<your-username>/submission-portal/venv`

### 6. Set environment variables
- In the Web tab, find **Environment variables**
- Add:
  - `SECRET_KEY` = a random long string (use any random password generator)
  - `ADMIN_USERNAME` = admin
  - `ADMIN_PASSWORD` = your-secure-password-here

### 7. Create needed folders
- In the Bash console:
```
cd ~/submission-portal
mkdir -p instance submissions
```

### 8. Reload and test
- Go back to the **Web** tab
- Click the green **Reload** button
- Visit your site at: `https://<your-username>.pythonanywhere.com`

## Free tier limits
- 512 MB disk space
- 200 CPU-seconds per day
- 1 web app
- Your site sleeps after ~3 months of inactivity (just log in to wake it)

## Notes
- The SQLite database auto-creates on first run (instance/submissions.db)
- Uploaded files go to submissions/ and persist across restarts
- The database and uploads survive restarts and reloads (persistent filesystem)