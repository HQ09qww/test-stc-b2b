import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from dotenv import load_dotenv
import uuid
import boto3
from botocore.client import Config


# โหลดตัวแปรสภาพแวดล้อมจากไฟล์ .env (สำหรับการรันในเครื่อง)
load_dotenv()

# --- สร้าง Flask app ก่อน db ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fwfregwqdsvqwddawfe')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///dev.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- ตั้งค่า Cloudflare R2 Credentials (ใช้ชื่อ key ที่ถูกต้อง) ---
R2_ACCESS_KEY_ID = os.environ.get('R2_ACCESS_KEY_ID')
R2_SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_ACCESS_KEY')
R2_ACCOUNT_ID = os.environ.get('R2_ACCOUNT_ID')
R2_BUCKET_NAME = os.environ.get('R2_BUCKET_NAME')
R2_PUBLIC_URL_BASE = os.environ.get('R2_PUBLIC_URL_BASE')



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
    image_url = db.Column(db.String(500), nullable=True) # URL ของรูปภาพใน R2
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<OtSlip {self.employee_id} - {self.employee_name} ({self.department}) on {self.ot_date}>'



# --- Routes (เส้นทางของ Web Application) ---




@app.route('/')
def index():
    search_query = request.args.get('search', '')
    # ดึงข้อมูลใบ OT ทั้งหมดจากฐานข้อมูล
    # เพิ่มฟังก์ชันค้นหา/กรองข้อมูล เฉพาะชื่อ/เลขพนักงาน
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
    app.run(debug=True)
