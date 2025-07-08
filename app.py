import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
# --- การตั้งค่าฐานข้อมูล ---
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///dev.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fwfregwqdsvqwddawfe')
db = SQLAlchemy(app)

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

# --- Model ฐานข้อมูลสำหรับใบ OT (เหมือนเดิม เพิ่ม employee_id) ---
class OtSlip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(20), nullable=False) # เพิ่มเลขพนักงาน
    employee_name = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(100), nullable=False)
    ot_date = db.Column(db.Date, nullable=False)
    hours = db.Column(db.Float, nullable=False)
    image_url = db.Column(db.String(500), nullable=True) # URL ของรูปภาพ
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<OtSlip {self.employee_id} - {self.employee_name} ({self.department}) on {self.ot_date}>'

# --- Routes (เส้นทางของ Web Application) ---

@app.route('/')
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
