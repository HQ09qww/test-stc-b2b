import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from dotenv import load_dotenv
import uuid # สำหรับสร้างชื่อไฟล์ที่ไม่ซ้ำกัน
import boto3 # สำหรับเชื่อมต่อกับ Cloudflare R2 (S3-compatible)
from botocore.client import Config # สำหรับกำหนด Endpoint ของ R2

# โหลดตัวแปรสภาพแวดล้อมจากไฟล์ .env (สำหรับการรันในเครื่อง)
load_dotenv()

app = Flask(__name__)

# --- การตั้งค่าฐานข้อมูล ---
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///dev.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- ตั้งค่า Flask Secret Key ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your_super_secret_key_please_change_this_in_production')

# --- ตั้งค่า Cloudflare R2 Credentials ---
# ดึงจาก Environment Variables (ควรตั้งค่าในไฟล์ .env หรือ Environment จริง)
R2_ACCESS_KEY_ID = os.environ.get('R2_ACCESS_KEY_ID')
R2_SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_ACCESS_KEY')
R2_ACCOUNT_ID = os.environ.get('R2_ACCOUNT_ID') # Account ID ของ Cloudflare
R2_BUCKET_NAME = os.environ.get('R2_BUCKET_NAME') # ชื่อ Bucket ของ R2
R2_PUBLIC_URL_BASE = os.environ.get('R2_PUBLIC_URL_BASE') # URL พื้นฐานสำหรับเข้าถึงรูปภาพแบบ Public (จากขั้นตอนที่ 5.4)


# --- Model ฐานข้อมูล (เหมือนเดิม) ---
class OtSlip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_name = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(100), nullable=False)
    ot_date = db.Column(db.Date, nullable=False)
    hours = db.Column(db.Float, nullable=False)
    image_url = db.Column(db.String(500), nullable=True) # จะเก็บ URL ของรูปใน R2
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<OtSlip {self.employee_name} ({self.department}) on {self.ot_date}>'

# --- สร้างตารางในฐานข้อมูล (ต้องรันครั้งแรกหรือเมื่อมีการเปลี่ยนแปลง Model) ---
with app.app_context():
    db.create_all()


# --- Routes ---

@app.route('/')
def index():
    ot_slips = OtSlip.query.order_by(OtSlip.ot_date.desc()).all()
    return render_template('index.html', ot_slips=ot_slips)

@app.route('/add', methods=['GET', 'POST'])
def add_ot_slip():
    departments = ["HR", "IT", "Sales", "Marketing", "Finance", "Production", "Other"]

    if request.method == 'POST':
        employee_name = request.form['employee_name']
        department = request.form['department']
        ot_date_str = request.form['ot_date']
        hours_str = request.form['hours']
        description = request.form.get('description')
        ot_date = datetime.strptime(ot_date_str, '%Y-%m-%d').date()

        image_url = None
        if 'ot_image' in request.files:
            file = request.files['ot_image']
            if file.filename != '':
                try:
                    # ตรวจสอบขนาดไฟล์ (เช่น ไม่เกิน 5MB)
                    # ต้องอ่านไฟล์ก่อนเพื่อตรวจสอบขนาด แล้วใช้ .seek(0) เพื่อรีเซ็ตก่อนอัปโหลด
                    file.seek(0, os.SEEK_END) # เลื่อนไปท้ายไฟล์
                    file_size = file.tell() # ได้ขนาดไฟล์
                    file.seek(0) # รีเซ็ตกลับไปต้นไฟล์

                    if file_size > 5 * 1024 * 1024: # 5MB
                        flash('ขนาดไฟล์รูปภาพต้องไม่เกิน 5 MB', 'error')
                        return render_template('add_ot.html', departments=departments)

                    # --- เชื่อมต่อและอัปโหลดไปยัง Cloudflare R2 ---
                    # Endpoint URL สำหรับ Cloudflare R2 (สำคัญมาก!)
                    # รูปแบบ: https://<ACCOUNT_ID>.r2.cloudflarestorage.com
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
                    unique_filename = f"ot_slip_{uuid.uuid4()}_{file.filename.replace(' ', '_')}" # แทนที่ช่องว่างในชื่อไฟล์

                    # อัปโหลดไฟล์ไปยัง R2
                    s3_client.upload_fileobj(
                        file, # ไฟล์อ็อบเจกต์ที่รับมาจาก Flask
                        R2_BUCKET_NAME, # ชื่อ Bucket ของ R2
                        unique_filename, # ชื่อไฟล์ที่จะใช้เก็บใน R2
                        ExtraArgs={
                            'ContentType': file.content_type # กำหนด Content-Type ของไฟล์
                        }
                    )
                    
                    # สร้าง URL สาธารณะของรูปภาพ
                    # R2_PUBLIC_URL_BASE คือ URL ที่คุณได้จาก Cloudflare (เช่น https://your-bucket.your-account-id.r2.cloudflarestorage.com)
                    # หรือ https://your-custom-domain.com/ (ถ้าคุณตั้งค่า Custom Domain)
                    if R2_PUBLIC_URL_BASE and not R2_PUBLIC_URL_BASE.endswith('/'):
                        R2_PUBLIC_URL_BASE += '/'
                    image_url = f"{R2_PUBLIC_URL_BASE}{unique_filename}"

                    flash(f'อัปโหลดไฟล์ {file.filename} สำเร็จ!', 'info')

                except Exception as e:
                    flash(f"เกิดข้อผิดพลาดในการอัปโหลดไฟล์ไปยัง Cloudflare R2: {e}", 'error')
                    image_url = None # ถ้าอัปโหลดล้มเหลว ไม่ต้องเก็บ URL


        try:
            hours = float(hours_str)
            if image_url is None and 'ot_image' in request.files and request.files['ot_image'].filename != '':
                # ถ้าผู้ใช้พยายามอัปโหลดรูปแต่เกิดข้อผิดพลาดในการอัปโหลด
                # เราจะยังไม่บันทึกข้อมูล OT Slip นี้
                return render_template('add_ot.html', departments=departments)

            new_ot_slip = OtSlip(
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
            flash('ชั่วโมง OT ไม่ถูกต้อง', 'error')
        except Exception as e:
            db.session.rollback()
            flash(f'เกิดข้อผิดพลาดในการบันทึกข้อมูล: {e}', 'error')

    return render_template('add_ot.html', departments=departments)

if __name__ == '__main__':
    app.run(debug=True)