import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from dotenv import load_dotenv
import uuid
import boto3
from botocore.client import Config
from werkzeug.security import generate_password_hash, check_password_hash # สำหรับเข้ารหัส/ตรวจสอบรหัสผ่าน
from functools import wraps # สำหรับสร้าง decorator @login_required

# โหลดตัวแปรสภาพแวดล้อมจากไฟล์ .env (สำหรับการรันในเครื่อง)
load_dotenv()
# --- การตั้งค่าฐานข้อมูล ---

db = SQLAlchemy(app)

# --- ตั้งค่า Flask Secret Key ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fwfregwqdsvqwddawfe')

# --- ตั้งค่า Cloudflare R2 Credentials ---
# ดึงจาก Environment Variables
R2_ACCESS_KEY_ID = os.environ.get('f38974467f3cc3f24aa8dbb144e56352')
R2_SECRET_ACCESS_KEY = os.environ.get('03b785eb5df51180f93787c85cf96ff77b1614113d3af3777b4ee3de3cd833c9')
R2_ACCOUNT_ID = os.environ.get('af83c7dc9757b49457b31c4791bdf16e') # Account ID ของ Cloudflare
R2_BUCKET_NAME = os.environ.get('test-stc-ot') # ชื่อ Bucket ของ R2
R2_PUBLIC_URL_BASE = os.environ.get('https://pub-dec3f8eb0f0a4b42becd17f19df20a4d.r2.dev') # URL

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
    search_query = request.args.get('search', '') # รับค่า search query
    
    # ดึงข้อมูลใบ OT ทั้งหมดจากฐานข้อมูล
    # เพิ่มฟังก์ชันค้นหา/กรองข้อมูล
    if search_query:
        ot_slips = OtSlip.query.filter(
            (OtSlip.employee_name.ilike(f'%{search_query}%')) | # ค้นหาจากชื่อพนักงาน
            (OtSlip.department.ilike(f'%{search_query}%')) | # ค้นหาจากแผนก
            (OtSlip.employee_id.ilike(f'%{search_query}%')) # ค้นหาจากเลขพนักงาน
        ).order_by(OtSlip.ot_date.desc()).all()
    else:
        ot_slips = OtSlip.query.order_by(OtSlip.ot_date.desc()).all()
        
    return render_template('index.html', ot_slips=ot_slips, search_query=search_query, username=session.get('username'))

@app.route('/add', methods=['GET', 'POST'])
@login_required # ต้อง Login ก่อนถึงจะเข้าถึงหน้านี้ได้
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
            if file.filename != '':
                try:
                    # ตรวจสอบขนาดไฟล์ (เช่น ไม่เกิน 5MB)
                    # ต้องอ่านไฟล์ก่อนเพื่อตรวจสอบขนาด แล้วใช้ .seek(0) เพื่อรีเซ็ตก่อนอัปโหลด
                    file.seek(0, os.SEEK_END) # เลื่อนไปท้ายไฟล์
                    file_size = file.tell() # ได้ขนาดไฟล์
                    file.seek(0) # รีเซ็ตกลับไปต้นไฟล์

                    if file_size == 0: # ตรวจสอบไฟล์ว่างเปล่า
                        flash('ไฟล์รูปภาพว่างเปล่า กรุณาเลือกไฟล์ใหม่', 'error')
                        return render_template('add_ot.html', departments=departments, employee_id=employee_id, employee_name=employee_name, department=department, ot_date=ot_date_str, hours=hours_str, description=description)
                    
                    if file_size > 5 * 1024 * 1024: # 5MB
                        flash('ขนาดไฟล์รูปภาพต้องไม่เกิน 5 MB', 'error')
                        return render_template('add_ot.html', departments=departments, employee_id=employee_id, employee_name=employee_name, department=department, ot_date=ot_date_str, hours=hours_str, description=description)

                    # --- เชื่อมต่อและอัปโหลดไปยัง Cloudflare R2 ---
                    r2_endpoint_url = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

                    s3_client = boto3.client(
                        's3',
                        endpoint_url=r2_endpoint_url,
                        aws_access_key_id=R2_ACCESS_KEY_ID,
                        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
                        config=Config(signature_version='s3v4') # R2 ใช้ signature version นี้
                    )

                    # สร้างชื่อไฟล์ที่ไม่ซ้ำกัน
                    # เช่น ot_slip_df7c4f4a-71dd-44de-9e2b-f8c0e64c3c3a_original_name.jpg
                    # เพิ่ม employee_id และ ot_date ในชื่อไฟล์เพื่อการจัดระเบียบที่ดีขึ้น
                    unique_filename = f"ot_slip_{employee_id}_{ot_date_str}_{uuid.uuid4()}_{file.filename.replace(' ', '_')}"

                    s3_client.upload_fileobj(
                        file, # ไฟล์อ็อบเจกต์ที่รับมาจาก Flask
                        R2_BUCKET_NAME, # ชื่อ Bucket ของ R2
                        unique_filename, # ชื่อไฟล์ที่จะใช้เก็บใน R2
                        ExtraArgs={
                            'ContentType': file.content_type # กำหนด Content-Type ของไฟล์
                        }
                    )
                    
                    # ตรวจสอบว่า R2_PUBLIC_URL_BASE มีค่าและลงท้ายด้วย / หรือไม่
                    if R2_PUBLIC_URL_BASE and not R2_PUBLIC_URL_BASE.endswith('/'):
                        R2_PUBLIC_URL_BASE += '/'
                    image_url = f"{R2_PUBLIC_URL_BASE}{unique_filename}"

                    flash(f'อัปโหลดไฟล์ {file.filename} สำเร็จ!', 'info')

                except Exception as e:
                    flash(f"เกิดข้อผิดพลาดในการอัปโหลดไฟล์ไปยัง Cloudflare R2: {e}", 'error')
                    image_url = None # ถ้าอัปโหลดล้มเหลว ไม่ต้องเก็บ URL
                    # หากเกิดข้อผิดพลาดในการอัปโหลดไฟล์ ให้คืนค่าฟอร์มพร้อมข้อมูลเดิม
                    return render_template('add_ot.html', departments=departments, employee_id=employee_id, employee_name=employee_name, department=department, ot_date=ot_date_str, hours=hours_str, description=description)


        try:
            ot_date = datetime.strptime(ot_date_str, '%Y-%m-%d').date()
            hours = float(hours_str)

            # ตรวจสอบว่าถ้ามีการเลือกไฟล์ แต่ image_url เป็น None (หมายถึงอัปโหลดล้มเหลว)
            if file and file.filename != '' and image_url is None:
                flash('ไม่สามารถบันทึกใบ OT ได้เนื่องจากอัปโหลดรูปภาพไม่สำเร็จ', 'error')
                return render_template('add_ot.html', departments=departments, employee_id=employee_id, employee_name=employee_name, department=department, ot_date=ot_date_str, hours=hours_str, description=description)

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
@login_required # ต้อง Login ก่อนถึงจะลบได้
def delete_ot(ot_id):
    ot_slip = OtSlip.query.get_or_404(ot_id)
    
    try:
        # ถ้ามีรูปภาพ ให้ลบออกจาก Cloudflare R2 ด้วย
        if ot_slip.image_url:
            # ดึงชื่อไฟล์จาก URL
            filename = os.path.basename(ot_slip.image_url)
            
            r2_endpoint_url = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
            s3_client = boto3.client(
                's3',
                endpoint_url=r2_endpoint_url,
                aws_access_key_id=R2_ACCESS_KEY_ID,
                aws_secret_access_key=R2_SECRET_ACCESS_KEY,
                config=Config(signature_version='s3v4')
            )
            s3_client.delete_object(Bucket=R2_BUCKET_NAME, Key=filename)
            flash(f'ลบรูปภาพ {filename} จาก Cloudflare R2 สำเร็จ!', 'info')

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
