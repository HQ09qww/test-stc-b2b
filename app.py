import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from dotenv import load_dotenv

# โหลดตัวแปรสภาพแวดล้อมจากไฟล์ .env (สำหรับการรันในเครื่อง)
load_dotenv()
# --- การตั้งค่าฐานข้อมูล ---

db = SQLAlchemy(app)

# --- ตั้งค่า Flask Secret Key ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fwfregwqdsvqwddawfe')

# --- การตั้งค่าฐานข้อมูล ---
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///dev.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- ตั้งค่า Flask Secret Key ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fwfregwqdsvqwddawfe')



# --- ข้อมูลพนักงานจำลอง (ในแอปจริงจะมาจากฐานข้อมูลพนักงาน) ---
# ใช้สำหรับฟังก์ชัน Auto-populate ชื่อและแผนก
EMPLOYEES = {
    "1001": {"name": "สมชาย ใจดี", "department": "Production"},
    "1002": {"name": "สมหญิง มีสุข", "department": "HR"},
    "1003": {"name": "สมศักดิ์ ขยัน", "department": "IT"},
    "1004": {"name": "สมศรี รุ่งเรือง", "department": "Sales"},
    "1005": {"name": "มานะ พัฒนา", "department": "Marketing"},
    "1006": {"name": "มานี เก่งกาจ", "department": "Finance"},
    # เพิ่มข้อมูลพนักงานอื่นๆ ที่นี่
}

# --- Model ฐานข้อมูลสำหรับผู้ใช้งาน (User) ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'

# --- Model ฐานข้อมูลสำหรับใบ OT (เหมือนเดิม เพิ่ม employee_id) ---
class OtSlip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(20), nullable=False) # เพิ่มเลขพนักงาน
    employee_name = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(100), nullable=False)
    ot_date = db.Column(db.Date, nullable=False)
    hours = db.Column(db.Float, nullable=False)
    image_url = db.Column(db.String(500), nullable=True) # URL ของรูปภาพใน R2
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<OtSlip {self.employee_id} - {self.employee_name} ({self.department}) on {self.ot_date}>'

# --- Decorator สำหรับตรวจสอบการ Login ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            flash('กรุณาเข้าสู่ระบบก่อน', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- Routes (เส้นทางของ Web Application) ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            session['logged_in'] = True
            session['username'] = user.username
            flash('เข้าสู่ระบบสำเร็จ!', 'success')
            return redirect(url_for('index'))
        else:
            flash('ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    flash('ออกจากระบบแล้ว', 'info')
    return redirect(url_for('login'))

# --- Route สำหรับสร้างผู้ใช้เริ่มต้น (สำหรับ Admin ในการตั้งค่าครั้งแรก) ---
# **สำคัญ:** ควรลบหรือปิดใช้งาน Route นี้หลังจากสร้างผู้ใช้ Admin เสร็จแล้ว
@app.route('/register_admin')
def register_admin():
    # ตรวจสอบว่ามีผู้ใช้แล้วหรือยัง
    if User.query.filter_by(username='admin').first():
        return "Admin user already exists. Please delete this route after initial setup."
    
    admin_user = User(username='admin')
    admin_user.set_password('admin_password') # **เปลี่ยนรหัสผ่านนี้เป็นรหัสผ่านที่ปลอดภัยของคุณ!**
    db.session.add(admin_user)
    db.session.commit()
    return "Admin user 'admin' created successfully. **Please change its password immediately and consider removing this route!**"


@app.route('/')
@login_required # ต้อง Login ก่อนถึงจะเข้าถึงหน้านี้ได้
def index():
    search_query = request.args.get('search', '')
    if search_query:
        ot_slips = OtSlip.query.filter(
            (OtSlip.employee_name.ilike(f'%{search_query}%')) |
            (OtSlip.employee_id.ilike(f'%{search_query}%'))
        ).order_by(OtSlip.ot_date.desc()).all()
    else:
        ot_slips = OtSlip.query.order_by(OtSlip.ot_date.desc()).all()
    return render_template('index.html', ot_slips=ot_slips, search_query=search_query)

@app.route('/add', methods=['GET', 'POST'])
def add_ot_slip():
    # กำหนดรายการแผนกที่คุณมี (สำหรับแสดงในกรณีที่ auto-populate ไม่ทำงาน หรือต้องการตัวเลือกอื่น)
    departments = ["HR", "IT", "Sales", "Marketing", "Finance", "Production", "Other"]

    if request.method == 'POST':
        employee_id = request.form['employee_id'].strip() # รับเลขพนักงานและตัดช่องว่าง
        employee_name = request.form['employee_name'].strip()
        department = request.form['department'].strip()
        ot_date_str = request.form['ot_date'].strip()
        hours_str = request.form['hours'].strip()
        description = request.form.get('description', '').strip() # ใช้ get เพื่อป้องกัน KeyError ถ้าไม่มี description

        # --- ตรวจสอบข้อมูลพนักงานที่ส่งมาจากฟอร์ม (ป้องกันการปลอมแปลง) ---
        if not employee_id:
            flash('กรุณากรอกเลขพนักงาน', 'error')
            return render_template('add_ot.html', departments=departments, employee_id=employee_id, employee_name=employee_name, department=department, ot_date=ot_date_str, hours=hours_str, description=description)

        if employee_id in EMPLOYEES:
            expected_name = EMPLOYEES[employee_id]["name"]
            expected_department = EMPLOYEES[employee_id]["department"]
            if employee_name != expected_name or department != expected_department:
                flash('ข้อมูลชื่อพนักงานหรือแผนกไม่ตรงกับเลขพนักงานที่ระบุ กรุณาตรวจสอบ', 'error')
                return render_template('add_ot.html', departments=departments, employee_id=employee_id, employee_name=employee_name, department=department, ot_date=ot_date_str, hours=hours_str, description=description)
        else:
            flash('ไม่พบเลขพนักงานนี้ในระบบ กรุณาตรวจสอบ', 'error')
            return render_template('add_ot.html', departments=departments, employee_id=employee_id, employee_name=employee_name, department=department, ot_date=ot_date_str, hours=hours_str, description=description)


        image_url = None
        file = None
        if 'ot_image' in request.files:
            file = request.files['ot_image']
            if file and file.filename:
                # บันทึกไฟล์ลงโฟลเดอร์ static/uploads (สร้างโฟลเดอร์นี้ถ้ายังไม่มี)
                upload_folder = os.path.join(app.root_path, 'static', 'uploads')
                os.makedirs(upload_folder, exist_ok=True)
                # สร้างชื่อไฟล์ไม่ซ้ำ
                from werkzeug.utils import secure_filename
                import time
                filename = f"{employee_id}_{int(time.time())}_{secure_filename(file.filename)}"
                file_path = os.path.join(upload_folder, filename)
                file.save(file_path)
                image_url = url_for('static', filename=f'uploads/{filename}')
        try:
            ot_date = datetime.strptime(ot_date_str, '%Y-%m-%d').date()
            hours = float(hours_str)



            new_ot_slip = OtSlip(
                employee_id=employee_id, # บันทึกเลขพนักงาน
                employee_name=employee_name,
                department=department,
                ot_date=ot_date,
                hours=hours,
                image_url=image_url, # เก็บ URL ของรูปใน R2
                description=description
            )
            db.session.add(new_ot_slip)
            db.session.commit()
            flash('เพิ่มใบ OT สำเร็จ!', 'success')
            return redirect(url_for('index'))
        except ValueError:
            flash('ชั่วโมง OT หรือวันที่ OT ไม่ถูกต้อง กรุณาตรวจสอบ', 'error')
            return render_template('add_ot.html', departments=departments, employee_id=employee_id, employee_name=employee_name, department=department, ot_date=ot_date_str, hours=hours_str, description=description)
        except Exception as e:
            db.session.rollback() # ถ้ามีข้อผิดพลาดในการบันทึกลง DB ให้ยกเลิกการเปลี่ยนแปลง
            flash(f'เกิดข้อผิดพลาดในการบันทึกข้อมูล: {e}', 'error')
            return render_template('add_ot.html', departments=departments, employee_id=employee_id, employee_name=employee_name, department=department, ot_date=ot_date_str, hours=hours_str, description=description)

    # สำหรับ GET request
    return render_template('add_ot.html', departments=departments)

# --- API Endpoint สำหรับค้นหาข้อมูลพนักงาน ---
@app.route('/api/employee_lookup/<employee_id>')
def employee_lookup(employee_id):
    employee_data = EMPLOYEES.get(employee_id)
    if employee_data:
        return jsonify({"found": True, "name": employee_data["name"], "department": employee_data["department"]})
    else:
        return jsonify({"found": False, "message": "ไม่พบเลขพนักงานนี้"})

# --- API Endpoint สำหรับลบใบ OT ---
@app.route('/delete_ot/<int:ot_id>', methods=['POST'])
def delete_ot(ot_id):
    ot_slip = OtSlip.query.get_or_404(ot_id)
    try:
        db.session.delete(ot_slip)
        db.session.commit()
        flash('ลบใบ OT สำเร็จ!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'เกิดข้อผิดพลาดในการลบใบ OT: {e}', 'error')
    return redirect(url_for('index'))


# --- สำหรับการรันแอปพลิเคชัน ---
if __name__ == '__main__':
    # **สำคัญ:** สำหรับการตั้งค่าผู้ใช้ Admin ครั้งแรก
    # ให้รันแอปในเครื่อง (python app.py) แล้วเข้า http://127.0.0.1:5000/register_admin
    # หลังจากสร้างแล้ว **ควรลบหรือคอมเมนต์ Route /register_admin นี้ออก** เพื่อความปลอดภัย
    app.run(debug=True)
