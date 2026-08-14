from flask import Flask, render_template, request, redirect, url_for, send_from_directory, session, flash, jsonify, make_response
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.utils import secure_filename
import os
import zipfile
import io
from dotenv import load_dotenv

# Import for C++ auto-grading
try:
    from code_grader import grade_cpp_file, format_grade_report
    HAS_CODE_GRADER = True
except ImportError:
    HAS_CODE_GRADER = False

# Import for DWG auto-grading
try:
    from dwg_grader import grade_dwg_file as grade_dwg, format_grade_report as format_dwg_report
    HAS_DWG_GRADER = True
except ImportError:
    HAS_DWG_GRADER = False

# Import for PDF auto-grading
try:
    from pdf_grader import grade_pdf_file, format_grade_report as format_pdf_report
    HAS_PDF_GRADER = True
except ImportError:
    HAS_PDF_GRADER = False

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', os.urandom(24))

_BASEDIR = os.path.abspath(os.path.dirname(__file__))

ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123')

UPLOAD_FOLDER = os.path.join(_BASEDIR, 'submissions')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {'dwg', 'dxf', 'cpp', 'c', 'h', 'hpp', 'pdf', 'docx', 'txt', 'zip','cxx'}
MAX_FILE_SIZE = 16 * 1024 * 1024
MAX_CONTENT_LENGTH = 50 * 1024 * 1024

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
# Use instance/ folder for the SQLite DB so it persists on PythonAnywhere
# and doesn't conflict with read-only app directories on PaaS platforms.
_INSTANCE_DIR = os.path.join(_BASEDIR, 'instance')
os.makedirs(_INSTANCE_DIR, exist_ok=True)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(_INSTANCE_DIR, 'submissions.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    code = db.Column(db.String(20))
    section = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'code': self.code or '',
            'section': self.section or '',
            'is_active': self.is_active,
            'display': f"{self.name} ({self.code or 'N/A'})" if self.code else self.name
        }

class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_name = db.Column(db.String(100), nullable=False)
    course_name = db.Column(db.String(100), nullable=False)
    activity_name = db.Column(db.String(100), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.Integer)
    file_path = db.Column(db.String(500), nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address = db.Column(db.String(45))
    grade = db.Column(db.Float, nullable=True)
    remarks = db.Column(db.String(500), nullable=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'student_name': self.student_name,
            'course_name': self.course_name,
            'activity_name': self.activity_name,
            'filename': self.filename,
            'original_filename': self.original_filename,
            'file_size': self.file_size,
            'file_path': self.file_path,
            'submitted_at': self.submitted_at.strftime('%Y-%m-%d %H:%M:%S'),
            'ip_address': self.ip_address,
            'grade': self.grade,
            'remarks': self.remarks or ''
        }

class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    due_date = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'course_id': self.course_id,
            'name': self.name,
            'due_date': self.due_date.strftime('%Y-%m-%d %H:%M') if self.due_date else None,
            'is_active': self.is_active,
            'is_past_due': self.due_date < datetime.utcnow() if self.due_date else False
        }

class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(500))

    @staticmethod
    def get(key, default=None):
        s = Setting.query.filter_by(key=key).first()
        return s.value if s else default

    @staticmethod
    def set(key, value):
        s = Setting.query.filter_by(key=key).first()
        if s:
            s.value = value
        else:
            s = Setting(key=key, value=value)
            db.session.add(s)
        db.session.commit()


def get_admin_credentials():
    """Read admin credentials from DB, fall back to env vars."""
    username = Setting.get('admin_username', ADMIN_USERNAME)
    password = Setting.get('admin_password', ADMIN_PASSWORD)
    return username, password


def init_db():
    with app.app_context():
        db.create_all()
        if Course.query.count() == 0:
            courses = [
                Course(name='Computer Programming 1', code='CPE 101', section='A'),
                Course(name='Computer Programming 2', code='CPE 102', section='A'),
                Course(name='Object Oriented Programming', code='CPE 121', section='A'),
            ]
            for course in courses:
                db.session.add(course)
            db.session.commit()
        
        if Activity.query.count() == 0:
            course = Course.query.first()
            activities = [
                Activity(course_id=course.id, name='Assignment 1', due_date=datetime.utcnow() + timedelta(days=7)),
                Activity(course_id=course.id, name='Lab 1', due_date=datetime.utcnow() + timedelta(days=3)),
            ]
            for activity in activities:
                db.session.add(activity)
            db.session.commit()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def sanitize_name(name):
    return "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).strip()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            flash('Please log in to access the admin panel', 'error')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    courses = Course.query.filter_by(is_active=True).all()
    activities = Activity.query.filter_by(is_active=True).order_by(Activity.due_date).all()
    courses_data = [c.to_dict() for c in courses]
    activities_data = [a.to_dict() for a in activities]
    return render_template('index.html', courses=courses_data, activities=activities_data,
                          admin_logged_in=session.get('logged_in', False))

@app.route('/submit', methods=['POST'])
def submit():
    student_name = request.form.get('student_name', '').strip()
    course_name = request.form.get('course_name', '').strip()
    activity_name = request.form.get('activity_name', '').strip()
    files = request.files.getlist('files')
    
    if not student_name or not course_name or not activity_name:
        return render_template('index.html', error='Please fill in all required fields', 
                             courses=get_courses(), activities=get_activities())
    
    if not files or all(f.filename == '' for f in files):
        return render_template('index.html', error='Please select at least one file', 
                             courses=get_courses(), activities=get_activities())
    
    activity = Activity.query.filter_by(name=activity_name).first()
    if activity and activity.due_date and datetime.utcnow() > activity.due_date:
        flash(f'Warning: The due date for this activity has passed!', 'warning')
    
    submitted_files = []
    errors = []
    
    sanitized_student = sanitize_name(student_name)
    sanitized_course = sanitize_name(course_name)
    sanitized_activity = sanitize_name(activity_name)
    folder_path = os.path.join(app.config['UPLOAD_FOLDER'], sanitized_course, sanitized_activity)
    os.makedirs(folder_path, exist_ok=True)
    
    for file in files:
        if file.filename == '':
            continue
        
        if not allowed_file(file.filename):
            errors.append(f"File type not allowed: {file.filename}")
            continue
        
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        
        if file_size > MAX_FILE_SIZE:
            errors.append(f"File too large: {file.filename} (max {MAX_FILE_SIZE // (1024*1024)}MB)")
            continue
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        original_filename = secure_filename(file.filename)
        filename = f"{timestamp}_{original_filename}"
        file_path = os.path.join(folder_path, filename)
        file.save(file_path)
        
        submission = Submission(
            student_name=student_name,
            course_name=course_name,
            activity_name=activity_name,
            filename=filename,
            original_filename=original_filename,
            file_size=file_size,
            file_path=os.path.join(sanitized_course, sanitized_activity, filename),
            ip_address=request.remote_addr
        )
        db.session.add(submission)
        submitted_files.append(original_filename)
    
    db.session.commit()
    
    if errors and not submitted_files:
        return render_template('index.html', error='; '.join(errors), 
                             courses=get_courses(), activities=get_activities())
    
    return render_template('success.html', 
                          student_name=student_name, 
                          course_name=course_name,
                          activity_name=activity_name, 
                          filenames=submitted_files,
                          errors=errors if errors else None)

@app.route('/activity/due-date/<name>')
def get_activity_due_date(name):
    activity = Activity.query.filter_by(name=name).first()
    if activity:
        return jsonify(activity.to_dict())
    return jsonify({'error': 'Activity not found'}), 404

@app.route('/api/activities')
def get_activities_by_course():
    import re
    course_display = request.args.get('course', '').strip()

    course = None
    if course_display:
        match = re.match(r'^(.+?)\s*\(([^)]+)\)$', course_display)
        if match:
            course_name = match.group(1).strip()
            course_code = match.group(2).strip()
            course = Course.query.filter(
                Course.name == course_name,
                Course.code == course_code
            ).first()
        else:
            course = Course.query.filter_by(name=course_display).first()

    if course:
        activities = Activity.query.filter_by(
            course_id=course.id,
            is_active=True
        ).order_by(Activity.due_date).all()
    else:
        activities = []

    return jsonify([a.to_dict() for a in activities])


@app.route('/api/students')
def get_students_by_course():
    """Return distinct student names who have submitted for a given course."""
    import re
    course_display = request.args.get('course', '').strip()

    if not course_display:
        return jsonify([])

    # Parse "Course Name (CODE)" format
    match = re.match(r'^(.+?)\s*\(([^)]+)\)$', course_display)
    if match:
        course_name = match.group(1).strip()
        course_code = match.group(2).strip()
        students = Submission.query.filter(
            Submission.course_name.like(f'%{course_name}%'),
            Submission.course_name.like(f'%{course_code}%')
        ).with_entities(Submission.student_name).distinct().order_by(Submission.student_name).all()
    else:
        students = Submission.query.filter(
            Submission.course_name.like(f'%{course_display}%')
        ).with_entities(Submission.student_name).distinct().order_by(Submission.student_name).all()

    return jsonify([s[0] for s in students])

@app.route('/submissions/<path:filename>')
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

@app.route('/admin/login')
def admin_login():
    if 'logged_in' in session:
        return redirect(url_for('admin'))
    return render_template('login.html')

@app.route('/admin/login', methods=['POST'])
def admin_login_post():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    
    valid_user, valid_pass = get_admin_credentials()
    if username == valid_user and password == valid_pass:
        session['logged_in'] = True
        session['username'] = username
        flash('Successfully logged in!', 'success')
        return redirect(url_for('admin'))
    else:
        flash('Invalid username or password', 'error')
        return redirect(url_for('admin_login'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    flash('Successfully logged out', 'success')
    return redirect(url_for('index'))

@app.route('/admin/settings', methods=['POST'])
@login_required
def admin_settings():
    current_user, current_pass = get_admin_credentials()
    old_password = request.form.get('old_password', '').strip()
    new_username = request.form.get('new_username', '').strip()
    new_password = request.form.get('new_password', '').strip()

    if old_password != current_pass:
        flash('Current password is incorrect.', 'error')
        return redirect(request.referrer or url_for('admin'))

    if not new_username or not new_password:
        flash('Username and password cannot be empty.', 'error')
        return redirect(request.referrer or url_for('admin'))

    Setting.set('admin_username', new_username)
    Setting.set('admin_password', new_password)
    session['username'] = new_username
    flash('Credentials updated successfully. Please use your new username and password next login.', 'success')
    return redirect(request.referrer or url_for('admin'))

@app.route('/admin')
@login_required
def admin():
    search_query = request.args.get('search', '').strip()
    course_filter = request.args.get('course', '').strip()
    activity_filter = request.args.get('activity', '').strip()
    
    query = Submission.query
    
    if search_query:
        query = query.filter(
            db.or_(
                Submission.student_name.ilike(f'%{search_query}%'),
                Submission.original_filename.ilike(f'%{search_query}%')
            )
        )
    
    if course_filter:
        query = query.filter_by(course_name=course_filter)
    
    if activity_filter:
        query = query.filter_by(activity_name=activity_filter)
    
    submissions = query.order_by(Submission.submitted_at.desc()).all()
    courses = Course.query.order_by(Course.name).all()
    all_courses = Course.query.order_by(Course.name).all()
    activities = Activity.query.order_by(Activity.name).all()
    all_activities = Activity.query.order_by(Activity.due_date).all()
    
    total_size = sum(s.file_size for s in submissions) if submissions else 0
    unique_students = len(set(s.student_name for s in submissions)) if submissions else 0
    
    return render_template('admin.html', 
                          submissions=[s.to_dict() for s in submissions],
                          courses=[c.to_dict() for c in courses],
                          all_courses=[c.to_dict() for c in all_courses],
                          activities=[a.to_dict() for a in activities],
                          all_activities=[a.to_dict() for a in all_activities],
                          stats={
                              'total': len(submissions),
                              'students': unique_students,
                              'storage': f"{total_size / (1024*1024):.2f} MB"
                          },
                          search_query=search_query,
                          course_filter=course_filter,
                          activity_filter=activity_filter)

@app.route('/admin/submission/<int:id>/delete', methods=['POST'])
@login_required
def delete_submission(id):
    submission = Submission.query.get_or_404(id)
    
    file_full_path = os.path.join(app.config['UPLOAD_FOLDER'], submission.file_path)
    if os.path.exists(file_full_path):
        os.remove(file_full_path)
    
    db.session.delete(submission)
    db.session.commit()
    
    flash(f'Submission deleted successfully', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/bulk-delete', methods=['POST'])
@login_required
def bulk_delete():
    ids = request.json.get('ids', [])
    deleted_count = 0
    
    for id in ids:
        submission = Submission.query.get(id)
        if submission:
            file_full_path = os.path.join(app.config['UPLOAD_FOLDER'], submission.file_path)
            if os.path.exists(file_full_path):
                os.remove(file_full_path)
            db.session.delete(submission)
            deleted_count += 1
    
    db.session.commit()
    return jsonify({'success': True, 'deleted': deleted_count})

@app.route('/admin/download/<int:id>')
@login_required
def download_single(id):
    submission = Submission.query.get_or_404(id)
    directory = os.path.join(app.config['UPLOAD_FOLDER'], 
                             os.path.dirname(submission.file_path))
    filename = os.path.basename(submission.file_path)
    return send_from_directory(directory, filename, as_attachment=True)

@app.route('/admin/bulk-download', methods=['POST'])
@login_required
def bulk_download():
    ids = request.json.get('ids', [])
    
    if not ids:
        return jsonify({'error': 'No files selected'}), 400
    
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for id in ids:
            submission = Submission.query.get(id)
            if submission:
                file_full_path = os.path.join(app.config['UPLOAD_FOLDER'], submission.file_path)
                if os.path.exists(file_full_path):
                    zf.write(file_full_path, submission.original_filename)
    
    memory_file.seek(0)
    response = make_response(memory_file.getvalue())
    response.headers['Content-Type'] = 'application/zip'
    response.headers['Content-Disposition'] = f'attachment; filename=submissions_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip'
    
    return response

@app.route('/admin/course/create', methods=['POST'])
@login_required
def create_course():
    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip()
    section = request.form.get('section', '').strip()
    
    if not name:
        flash('Course name is required', 'error')
        return redirect(url_for('admin'))
    
    existing = Course.query.filter_by(name=name).first()
    if existing:
        existing.code = code
        existing.section = section
        flash(f'Course "{name}" updated', 'success')
    else:
        course = Course(name=name, code=code, section=section)
        db.session.add(course)
        flash(f'Course "{name}" created', 'success')
    
    db.session.commit()
    return redirect(url_for('admin'))

@app.route('/admin/course/<int:id>/update', methods=['POST'])
@login_required
def update_course(id):
    course = Course.query.get_or_404(id)
    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip()
    section = request.form.get('section', '').strip()
    
    if name:
        course.name = name
    course.code = code
    course.section = section
    
    db.session.commit()
    flash(f'Course "{course.name}" updated', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/course/<int:id>/delete', methods=['POST'])
@login_required
def delete_course(id):
    course = Course.query.get_or_404(id)
    Activity.query.filter_by(course_id=id).delete()
    db.session.delete(course)
    db.session.commit()
    flash(f'Course deleted', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/activity/create', methods=['POST'])
@login_required
def create_activity():
    name = request.form.get('name', '').strip()
    course_id = request.form.get('course_id', '').strip()
    due_date = request.form.get('due_date', '').strip()
    
    if not name:
        flash('Activity name is required', 'error')
        return redirect(url_for('admin'))
    
    due_date_obj = None
    if due_date:
        try:
            due_date_obj = datetime.strptime(due_date, '%Y-%m-%dT%H:%M')
        except ValueError:
            flash('Invalid date format', 'error')
            return redirect(url_for('admin'))
    
    course_id_int = int(course_id) if course_id and course_id.isdigit() else None
    
    existing = Activity.query.filter_by(name=name).first()
    if existing:
        existing.due_date = due_date_obj
        existing.course_id = course_id_int
        flash(f'Activity "{name}" updated', 'success')
    else:
        activity = Activity(course_id=course_id_int, name=name, due_date=due_date_obj)
        db.session.add(activity)
        flash(f'Activity "{name}" created', 'success')
    
    db.session.commit()
    return redirect(url_for('admin'))

@app.route('/admin/activity/<int:id>/update', methods=['POST'])
@login_required
def update_activity(id):
    activity = Activity.query.get_or_404(id)
    name = request.form.get('name', '').strip()
    course_id = request.form.get('course_id', '').strip()
    due_date = request.form.get('due_date', '').strip()
    
    if name:
        activity.name = name
    
    if course_id:
        activity.course_id = int(course_id)
    
    if due_date:
        try:
            activity.due_date = datetime.strptime(due_date, '%Y-%m-%dT%H:%M')
        except ValueError:
            flash('Invalid date format', 'error')
            return redirect(url_for('admin'))
    
    db.session.commit()
    flash(f'Activity "{activity.name}" updated', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/activity/<int:id>/delete', methods=['POST'])
@login_required
def delete_activity(id):
    activity = Activity.query.get_or_404(id)
    db.session.delete(activity)
    db.session.commit()
    flash(f'Activity deleted', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/stats')
@login_required
def get_stats():
    total = Submission.query.count()
    students = len(set(s.student_name for s in Submission.query.all()))
    activities = Activity.query.count()
    total_size = sum(s.file_size or 0 for s in Submission.query.all())
    
    recent = Submission.query.order_by(Submission.submitted_at.desc()).limit(5).all()
    
    return jsonify({
        'total': total,
        'students': students,
        'activities': activities,
        'storage_mb': round(total_size / (1024*1024), 2),
        'recent': [s.to_dict() for s in recent]
    })

@app.route('/admin/grade', methods=['POST'])
@login_required
def save_grade():
    data = request.get_json()
    submission_id = data.get('id')
    grade = data.get('grade')
    remarks = data.get('remarks', '').strip()

    if not submission_id:
        return jsonify({'success': False, 'error': 'Missing submission ID'}), 400

    submission = Submission.query.get(submission_id)
    if not submission:
        return jsonify({'success': False, 'error': 'Submission not found'}), 404

    if grade is not None and grade != '':
        try:
            submission.grade = float(grade)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Grade must be a number'}), 400
    else:
        submission.grade = None

    submission.remarks = remarks or None
    db.session.commit()

    return jsonify({'success': True, 'grade': submission.grade, 'remarks': submission.remarks or ''})

@app.route('/admin/bulk-grade', methods=['POST'])
@login_required
def bulk_grade():
    grades_data = request.get_json().get('grades', [])
    updated = 0
    for item in grades_data:
        submission = Submission.query.get(item.get('id'))
        if submission:
            g = item.get('grade')
            if g is not None and g != '':
                try:
                    submission.grade = float(g)
                except (ValueError, TypeError):
                    continue
            else:
                submission.grade = None
            submission.remarks = item.get('remarks', '').strip() or None
            updated += 1
    db.session.commit()
    return jsonify({'success': True, 'updated': updated})

@app.route('/admin/grades')
@login_required
def grades_page():
    course_filter = request.args.get('course', '').strip()
    activity_filter = request.args.get('activity', '').strip()

    query = Submission.query
    if course_filter:
        query = query.filter_by(course_name=course_filter)
    if activity_filter:
        query = query.filter_by(activity_name=activity_filter)

    submissions = query.order_by(
        Submission.course_name,
        Submission.activity_name,
        Submission.student_name
    ).all()

    courses = Course.query.order_by(Course.name).all()
    activities = Activity.query.order_by(Activity.name).all()

    return render_template('grades.html',
                          submissions=[s.to_dict() for s in submissions],
                          courses=[c.to_dict() for c in courses],
                          activities=[a.to_dict() for a in activities],
                          course_filter=course_filter,
                          activity_filter=activity_filter)


@app.route('/admin/classlist')
@login_required
def classlist():
    course_filter = request.args.get('course', '').strip()
    sort_order = request.args.get('sort', 'name').strip()
    
    # Get all distinct students grouped by course
    courses = Course.query.order_by(Course.name).all()
    
    # Build section data
    sections = []
    for course in courses:
        # Determine the display name for this course
        display_name = f"{course.name} ({course.code})" if course.code else course.name
        
        # Get distinct students for this course
        # Match on course_name field in submissions
        if course.code:
            students = Submission.query.filter(
                Submission.course_name.like(f'%{course.name}%'),
                Submission.course_name.like(f'%{course.code}%')
            ).with_entities(Submission.student_name).distinct().order_by(Submission.student_name).all()
        else:
            students = Submission.query.filter_by(
                course_name=course.name
            ).with_entities(Submission.student_name).distinct().order_by(Submission.student_name).all()
        
        student_names = [s[0] for s in students]
        if student_names:
            # Count submissions and graded
            total = Submission.query.filter(
                Submission.course_name.like(f'%{course.name}%'),
                Submission.course_name.like(f'%{course.code}%') if course.code else True
            ).filter(Submission.student_name.in_(student_names)).count()
            
            graded = Submission.query.filter(
                Submission.course_name.like(f'%{course.name}%'),
                Submission.course_name.like(f'%{course.code}%') if course.code else True
            ).filter(
                Submission.student_name.in_(student_names),
                Submission.grade.isnot(None)
            ).count()
            
            sections.append({
                'name': display_name,
                'code': course.code or '',
                'student_count': len(student_names),
                'students': student_names,
                'total': total,
                'graded': graded
            })
    
    # Filter by course code if requested
    if course_filter:
        sections = [s for s in sections if course_filter.lower() in s['code'].lower() or course_filter.lower() in s['name'].lower()]
    
    # Sort
    if sort_order == 'count':
        sections.sort(key=lambda s: s['student_count'], reverse=True)
    elif sort_order == 'code':
        sections.sort(key=lambda s: s['code'])
    else:
        sections.sort(key=lambda s: s['name'])
    
    # Get unique course codes for filter dropdown
    all_codes = sorted(set(s['code'] for s in sections if s['code']))
    
    return render_template('classlist.html',
                          sections=sections,
                          course_filter=course_filter,
                          sort_order=sort_order,
                          all_codes=all_codes)


@app.route('/admin/class-record')
@login_required
def class_record():
    from collections import defaultdict
    
    # Custom sort order per section (matches the user's roster)
    sort_order_map = {
        'BSABE': {name: i for i, name in enumerate([
            'Bongue, Aaron Jay Tabigue', 'Dillera, Ronmark Salapar', 'Dongon, Jaymark Canale',
            'Lepiten, Joryl Abunda', 'Puti, Antonio Elvis Capili', 'Rejuso, John Caesar Glen-Eli Rondina',
            'Torres, Edrian Cris Galimba', 'Trabado, Mark Angelo Sanginez', 'Atacador, Mitzi Samson',
            'Capili, Antonia May Itang', 'Dela Cruz, Kassandra Adelan', 'Gimao, Maricel David',
            'Latagan, Lea Mae Almocera', 'Lerit, Shenamae Monterola', 'Magallanes, Jessa Mae Consulta',
            'Malunes, Kristena Mae Aballa', 'Rodriguez, Bianca Marie Rejuso', 'Torrefiel, Lea Gaylan',
        ])},
        'BSME': {name: i for i, name in enumerate([
            'Amican, Mark Aljon Rom', 'Cajurao, Frenz Erween Cristobal', 'Casilao, Jerick Mamac',
            'Cinco, Ervin Generoso', 'Cinco, Niño Ace Laurio', 'De Arce, Raymund Niño Bautista',
            'Hibo, Andrew Van Seman', 'Magalang, Neal Justin Romano', 'Marzan, Kelly Roland Grajo',
            'Taño, Charles Kent Dalanon', 'Valladores, Diether Legarda', 'Alfabete, Monica Carmen',
            'Amador, Jasmin Bello', 'Rubia, Cheenneth Capinig',
        ])},
        'BSChE': {name: i for i, name in enumerate([
            'Altarejos, Ajboy Mancio', 'Magallanes, Blaire Joram Antoniza', 'Mingoy, Reiniel Esquilona',
            'Rubis, Jericho Rodriguez', 'Tacdag, Ivan Magalang', 'Arcenal, Divine Reyna Bayagosa',
            'Azuero, Carshena Regala', 'Formarejo, Clarisse Gail', 'Rabino, Evelyn Acosta',
            'Sinadjan, Jenerose Mangubat', 'Ubaldo, Joyce Espinosa',
        ])},
        'BSCpE 1': {name: i for i, name in enumerate([
            'Esparagal, Kristelle Joy Almonia',
        ])},
    }
    
    course_filter = request.args.get('course', '').strip()
    courses = Course.query.order_by(Course.name).all()
    course_data = []
    all_codes = []
    
    for course in courses:
        if course.code:
            students = Submission.query.filter(
                Submission.course_name.like(f'%{course.name}%'),
                Submission.course_name.like(f'%{course.code}%')
            ).with_entities(Submission.student_name).distinct().order_by(Submission.student_name).all()
        else:
            students = Submission.query.filter_by(
                course_name=course.name
            ).with_entities(Submission.student_name).distinct().order_by(Submission.student_name).all()
        
        student_names = [s[0] for s in students]
        if not student_names:
            continue
        
        if course.code:
            activities = Submission.query.filter(
                Submission.course_name.like(f'%{course.name}%'),
                Submission.course_name.like(f'%{course.code}%'),
                Submission.student_name.in_(student_names)
            ).with_entities(Submission.activity_name).distinct().order_by(Submission.activity_name).all()
        else:
            activities = Submission.query.filter(
                Submission.course_name == course.name,
                Submission.student_name.in_(student_names)
            ).with_entities(Submission.activity_name).distinct().order_by(Submission.activity_name).all()
        
        activity_names = [a[0] for a in activities]
        
        student_records = []
        for student in student_names:
            if course.code:
                subs = Submission.query.filter(
                    Submission.course_name.like(f'%{course.name}%'),
                    Submission.course_name.like(f'%{course.code}%'),
                    Submission.student_name == student
                ).with_entities(Submission.activity_name, Submission.grade).all()
            else:
                subs = Submission.query.filter(
                    Submission.course_name == course.name,
                    Submission.student_name == student
                ).with_entities(Submission.activity_name, Submission.grade).all()
            
            grades = {}
            for act, grade in subs:
                if act not in grades:
                    grades[act] = []
                if grade is not None:
                    grades[act].append(grade)
            
            condensed = {}
            for act, g_list in grades.items():
                if g_list:
                    unique = list(set(g_list))
                    condensed[act] = round(sum(unique) / len(unique), 1)
                else:
                    condensed[act] = None
            
            student_records.append({'name': student, 'grades': condensed})
        
        # Apply custom sort order
        student_records.sort(key=lambda s: sort_order_map.get(course.name, {}).get(s['name'], 999))
        
        all_codes.append(course.code or course.name)
        course_data.append({
            'name': f"{course.name} ({course.code})" if course.code else course.name,
            'code': course.code or '',
            'activities': activity_names,
            'students': student_records,
            'student_count': len(student_names)
        })
    
    if course_filter:
        course_data = [c for c in course_data if course_filter.lower() in c['code'].lower() or course_filter.lower() in c['name'].lower()]
    
    return render_template('class_record.html',
                          courses=course_data,
                          course_filter=course_filter,
                          all_codes=sorted(set(all_codes)))


@app.route('/admin/auto-grade/<int:id>', methods=['POST'])
@login_required
def auto_grade(id):
    submission = Submission.query.get_or_404(id)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], submission.file_path)

    if not os.path.exists(filepath):
        return jsonify({'success': False, 'error': 'File not found on disk'}), 404

    ext = os.path.splitext(submission.original_filename.lower())[1]

    # --- C/C++ files ---
    if ext in ('.cpp', '.c', '.h', '.hpp', '.cxx'):
        if not HAS_CODE_GRADER:
            return jsonify({'success': False, 'error': 'Code grader module not available'}), 500
        try:
            result = grade_cpp_file(filepath)
            report = format_grade_report(result)
        except Exception as e:
            return jsonify({'success': False, 'error': f'C++ grading error: {str(e)}'}), 500

    # --- DWG/DXF files ---
    elif ext in ('.dwg', '.dxf'):
        if not HAS_DWG_GRADER:
            return jsonify({'success': False, 'error': 'DWG grader module not available'}), 500
        try:
            result = grade_dwg(filepath)
            report = format_dwg_report(result)
        except Exception as e:
            return jsonify({'success': False, 'error': f'DWG grading error: {str(e)}'}), 500

    # --- PDF files ---
    elif ext == '.pdf':
        if not HAS_PDF_GRADER:
            return jsonify({'success': False, 'error': 'PDF grader module not available'}), 500
        try:
            result = grade_pdf_file(filepath)
            report = format_pdf_report(result)
        except Exception as e:
            return jsonify({'success': False, 'error': f'PDF grading error: {str(e)}'}), 500

    else:
        return jsonify({'success': False, 'error': f'Auto-grade not supported for {ext} files'}), 400

    # Save the grade and detailed breakdown as remarks
    submission.grade = float(result['score'])
    submission.remarks = report
    db.session.commit()

    return jsonify({
        'success': True,
        'grade': result['score'],
        'raw_score': result['raw_score'],
        'bonus': result['bonus'],
        'breakdown': result['breakdown'],
        'details': result['details'],
        'remarks': report
    })


@app.route('/admin/view-code/<int:id>')
@login_required
def view_code(id):
    submission = Submission.query.get_or_404(id)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], submission.file_path)

    if not os.path.exists(filepath):
        return jsonify({'success': False, 'error': 'File not found on disk'}), 404

    ext = os.path.splitext(submission.original_filename.lower())[1]
    if ext not in ('.cpp', '.c', '.h', '.hpp', '.cxx'):
        return jsonify({'success': False, 'error': 'Viewer only supports C/C++ files'}), 400

    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

    return jsonify({
        'success': True,
        'filename': submission.original_filename,
        'student': submission.student_name,
        'activity': submission.activity_name,
        'lines': len(content.split('\n')),
        'content': content
    })


@app.route('/admin/view-file/<int:id>')
@login_required
def view_file(id):
    """Serve a submitted file inline (for PDF viewing in browser)."""
    submission = Submission.query.get_or_404(id)
    directory = os.path.join(app.config['UPLOAD_FOLDER'],
                             os.path.dirname(submission.file_path))
    filename = os.path.basename(submission.file_path)
    return send_from_directory(directory, filename, as_attachment=False)


@app.errorhandler(413)
def request_entity_too_large(error):
    flash('File too large. Maximum size is 50MB total.', 'error')
    return redirect(url_for('index'))

def get_activities():
    return [a.to_dict() for a in Activity.query.filter_by(is_active=True).order_by(Activity.due_date).all()]

def get_courses():
    return [c.to_dict() for c in Course.query.filter_by(is_active=True).order_by(Course.name).all()]


@app.route('/check')
def check_submissions():
    """Student-facing page to look up their own submissions by name."""
    student_name = request.args.get('name', '').strip()
    course_filter = request.args.get('course', '').strip()

    submissions = []
    if student_name:
        query = Submission.query.filter(Submission.student_name.ilike(f'%{student_name}%'))
        if course_filter:
            query = query.filter(Submission.course_name == course_filter)
        submissions = query.order_by(Submission.submitted_at.desc()).all()

    courses = Course.query.filter_by(is_active=True).order_by(Course.name).all()
    courses_data = [c.to_dict() for c in courses]

    return render_template('check.html',
                          submissions=[s.to_dict() for s in submissions],
                          courses=courses_data,
                          search_name=student_name,
                          course_filter=course_filter,
                          admin_logged_in=session.get('logged_in', False))

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
