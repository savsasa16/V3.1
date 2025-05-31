from flask import Flask, render_template, request, redirect, url_for, flash, g, send_file, current_app
import database
import pandas as pd
from io import BytesIO
from werkzeug.utils import secure_filename
import os
import sqlite3
from datetime import datetime
import pytz
from collections import defaultdict
import re

app = Flask(__name__)
# **สำคัญมาก: เปลี่ยน 'your_super_secret_key_here_please_change_this_to_a_complex_random_string' เป็นคีย์ลับที่ซับซ้อนของคุณเอง!**
# คุณสามารถสร้างคีย์ลับที่ซับซ้อนได้โดยใช้ Python prompt:
# import os
# os.urandom(24).hex()
app.secret_key = 'your_super_secret_key_here_please_change_this_to_a_complex_random_string'
app.config['UPLOAD_FOLDER'] = 'uploads' 
app.config['WHEEL_IMAGE_FOLDER'] = 'static/images/wheels' 

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['WHEEL_IMAGE_FOLDER'], exist_ok=True)

ALLOWED_EXCEL_EXTENSIONS = {'xlsx', 'xls'}
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_excel_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXCEL_EXTENSIONS

def allowed_image_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS

def get_db():
    if 'db' not in g:
        g.db = database.get_db_connection()
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def setup_database():
    with app.app_context():
        conn = get_db()
        database.init_db(conn)
        close_db()

def get_bkk_time():
    bkk_tz = pytz.timezone('Asia/Bangkok')
    return datetime.now(bkk_tz)

# Custom Jinja2 Filter for Thai Number Formatting (no decimals)
def format_thai_number(value):
    if value is None:
        return "-"
    
    # Try to convert to float/int to handle numeric types
    try:
        f_value = float(value)
        # Check if it's an integer value (e.g., 2025.0, 1000.0)
        if f_value.is_integer():
            return f"{int(f_value):,}" # Format as integer with comma
        else:
            return f"{f_value:,.2f}" # Keep 2 decimal places if it's truly a float (though requirement was no decimals, this is safer for general prices)
    except (ValueError, TypeError):
        # If it's not a number (e.g., "0125" as a string for year), return as is
        return str(value)

app.jinja_env.filters['th_num'] = format_thai_number

@app.context_processor
def inject_global_data():
    return dict(get_bkk_time=get_bkk_time)

@app.route('/')
def index():
    conn = get_db()
    
    tire_query = request.args.get('tire_query', '').strip()
    tire_selected_brand = request.args.get('tire_brand_filter', 'all').strip()
    
    all_tires = database.get_all_tires(conn, query=tire_query, brand_filter=tire_selected_brand)
    available_tire_brands = database.get_all_tire_brands(conn)

    # Sort tires by model and then by size (R14, R15 numerically)
    def tire_size_sort_key(tire):
        s_size = tire['size']
        match = re.search(r'R(\d+)', s_size) # Extract numeric part after 'R'
        if match:
            return int(match.group(1))
        return float('inf') # Put tires without 'R' at the end (large number to sort them last)

    tires_by_brand = defaultdict(list)
    for tire in all_tires:
        tires_by_brand[tire['brand']].append(tire)
    
    sorted_tire_brands = sorted(tires_by_brand.keys())

    # Apply secondary sort by size within each brand group
    for brand in sorted_tire_brands:
        tires_by_brand[brand].sort(key=tire_size_sort_key)


    wheel_query = request.args.get('wheel_query', '').strip()
    wheel_selected_brand = request.args.get('wheel_brand_filter', 'all').strip()

    all_wheels = database.get_all_wheels(conn, query=wheel_query, brand_filter=wheel_selected_brand)
    available_wheel_brands = database.get_all_wheel_brands(conn)
    
    wheels_by_brand = defaultdict(list)
    for wheel in all_wheels:
        wheels_by_brand[wheel['brand']].append(wheel)

    sorted_wheel_brands = sorted(wheels_by_brand.keys())

    active_tab = request.args.get('tab', 'tires')

    return render_template('index.html', 
                           tires=all_tires, 
                           tires_by_brand=tires_by_brand, 
                           sorted_tire_brands=sorted_tire_brands, 
                           tire_query=tire_query,
                           available_tire_brands=available_tire_brands,
                           tire_selected_brand=tire_selected_brand,
                           
                           wheels_by_brand=wheels_by_brand,
                           sorted_wheel_brands=sorted_wheel_brands,
                           wheel_query=wheel_query,
                           available_wheel_brands=available_wheel_brands,
                           wheel_selected_brand=wheel_selected_brand,
                           
                           active_tab=active_tab)

# --- Promotions Routes ---
@app.route('/promotions')
def promotions():
    conn = get_db()
    all_promotions = database.get_all_promotions(conn, include_inactive=True) 
    return render_template('promotions.html', promotions=all_promotions)

@app.route('/add_promotion', methods=('GET', 'POST'))
def add_promotion():
    if request.method == 'POST':
        name = request.form['name'].strip()
        promo_type = request.form['type'].strip()
        value1 = request.form['value1'].strip()
        value2 = request.form.get('value2', '').strip()
        is_active = request.form.get('is_active') == '1' 

        if not name or not promo_type or not value1:
            flash('กรุณากรอกข้อมูลโปรโมชันให้ครบถ้วน', 'danger')
        else:
            try:
                value1 = float(value1)
                value2 = float(value2) if value2 else None
                
                if promo_type == 'buy_x_get_y' and (value2 is None or value1 <= 0 or value2 <= 0):
                    raise ValueError("สำหรับ 'ซื้อ X แถม Y' โปรดระบุ X และ Y ที่มากกว่า 0")
                elif promo_type == 'percentage_discount' and (value1 <= 0 or value1 > 100):
                    raise ValueError("ส่วนลดเปอร์เซ็นต์ต้องอยู่ระหว่าง 0-100")
                elif promo_type == 'fixed_price_per_item' and value1 <= 0:
                    raise ValueError("ราคาพิเศษต้องมากกว่า 0")

                conn = get_db()
                database.add_promotion(conn, name, promo_type, value1, value2, is_active)
                flash('เพิ่มโปรโมชันใหม่สำเร็จ!', 'success')
                return redirect(url_for('promotions'))
            except ValueError as e:
                flash(f'ข้อมูลไม่ถูกต้อง: {e}', 'danger')
            except sqlite3.IntegrityError:
                flash(f'ชื่อโปรโมชัน "{name}" มีอยู่ในระบบแล้ว', 'warning')
            except Exception as e:
                flash(f'เกิดข้อผิดพลาดในการเพิ่มโปรโมชัน: {e}', 'danger')
    
    return render_template('add_promotion.html')

@app.route('/edit_promotion/<int:promo_id>', methods=('GET', 'POST'))
def edit_promotion(promo_id):
    conn = get_db()
    promotion = database.get_promotion(conn, promo_id)

    if promotion is None:
        flash('ไม่พบโปรโมชันที่ระบุ', 'danger')
        return redirect(url_for('promotions'))

    if request.method == 'POST':
        name = request.form['name'].strip()
        promo_type = request.form['type'].strip()
        value1 = request.form['value1'].strip()
        value2 = request.form.get('value2', '').strip()
        is_active = request.form.get('is_active') == '1'

        if not name or not promo_type or not value1:
            flash('กรุณากรอกข้อมูลโปรโมชันให้ครบถ้วน', 'danger')
        else:
            try:
                value1 = float(value1)
                value2 = float(value2) if value2 else None

                if promo_type == 'buy_x_get_y' and (value2 is None or value1 <= 0 or value2 <= 0):
                    raise ValueError("สำหรับ 'ซื้อ X แถม Y' โปรดระบุ X และ Y ที่มากกว่า 0")
                elif promo_type == 'percentage_discount' and (value1 <= 0 or value1 > 100):
                    raise ValueError("ส่วนลดเปอร์เซ็นต์ต้องอยู่ระหว่าง 0-100")
                elif promo_type == 'fixed_price_per_item' and value1 <= 0:
                    raise ValueError("ราคาพิเศษต้องมากกว่า 0")

                database.update_promotion(conn, promo_id, name, promo_type, value1, value2, is_active)
                flash('แก้ไขโปรโมชันสำเร็จ!', 'success')
                return redirect(url_for('promotions'))
            except ValueError as e:
                flash(f'ข้อมูลไม่ถูกต้อง: {e}', 'danger')
            except sqlite3.IntegrityError:
                flash(f'ชื่อโปรโมชัน "{name}" มีอยู่ในระบบแล้ว', 'warning')
            except Exception as e:
                flash(f'เกิดข้อผิดพลาดในการแก้ไขโปรโมชัน: {e}', 'danger')

    return render_template('edit_promotion.html', promotion=promotion)

@app.route('/delete_promotion/<int:promo_id>', methods=('POST',))
def delete_promotion(promo_id):
    conn = get_db()
    promotion = database.get_promotion(conn, promo_id)

    if promotion is None:
        flash('ไม่พบโปรโมชันที่ระบุ', 'danger')
    else:
        try:
            database.delete_promotion(conn, promo_id)
            flash('ลบโปรโมชันสำเร็จ! สินค้าที่เคยใช้โปรโมชันนี้จะถูกตั้งค่าโปรโมชันเป็น "ไม่มี"', 'success')
        except Exception as e:
            flash(f'เกิดข้อผิดพลาดในการลบโปรโมชัน: {e}', 'danger')
    
    return redirect(url_for('promotions'))


# --- Tire Routes (Adjusted for promotion_id and year_of_manufacture as TEXT) ---
@app.route('/add_item', methods=('GET', 'POST'))
def add_item():
    conn = get_db()
    # current_year is not directly used for year_of_manufacture input anymore
    # but might be used for max date or other purposes, so keep it for now.
    current_year = get_bkk_time().year 
    form_data = None 
    active_tab = request.args.get('tab', 'tire') 

    all_promotions = database.get_all_promotions(conn, include_inactive=False) 

    if request.method == 'POST':
        submit_type = request.form.get('submit_type')
        form_data = request.form 

        if submit_type == 'add_tire':
            brand = request.form['brand'].strip()
            model = request.form['model'].strip()
            size = request.form['size'].strip()
            quantity = request.form['quantity'] 
            
            cost_sc = request.form.get('cost_sc') 
            price_per_item = request.form['price_per_item'] 
            
            cost_dunlop = request.form.get('cost_dunlop')
            cost_online = request.form.get('cost_online')
            wholesale_price1 = request.form.get('wholesale_price1')
            wholesale_price2 = request.form.get('wholesale_price2')
            
            promotion_id = request.form.get('promotion_id') 
            if promotion_id == 'none' or not promotion_id:
                promotion_id_db = None
            else:
                promotion_id_db = int(promotion_id)

            year_of_manufacture = request.form.get('year_of_manufacture', '').strip() 

            if not brand or not model or not size or not quantity or not price_per_item: 
                flash('กรุณากรอกข้อมูลยางให้ครบถ้วนในช่องที่มีเครื่องหมาย *', 'danger')
                active_tab = 'tire' 
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)
            
            try:
                quantity = int(quantity)
                price_per_item = float(price_per_item) 

                cost_sc = float(cost_sc) if cost_sc and cost_sc.strip() else None
                cost_dunlop = float(cost_dunlop) if cost_dunlop and cost_dunlop.strip() else None
                cost_online = float(cost_online) if cost_online and cost_online.strip() else None
                wholesale_price1 = float(wholesale_price1) if wholesale_price1 and wholesale_price1.strip() else None
                wholesale_price2 = float(wholesale_price2) if wholesale_price2 and wholesale_price2.strip() else None
                
                # year_of_manufacture is TEXT in DB, so keep as string.
                # If it's empty, store as None
                year_of_manufacture_db = year_of_manufacture if year_of_manufacture else None


                database.add_tire(conn, brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, 
                                  wholesale_price1, wholesale_price2, price_per_item, 
                                  promotion_id_db, 
                                  year_of_manufacture_db) 
                flash('เพิ่มยางใหม่สำเร็จ!', 'success')
                return redirect(url_for('add_item', tab='tire'))

            except ValueError:
                flash('ข้อมูลตัวเลขไม่ถูกต้อง กรุณาตรวจสอบ', 'danger')
                active_tab = 'tire'
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)
            except sqlite3.IntegrityError:
                flash(f'ยางยี่ห้อ {brand} รุ่น {model} เบอร์ {size} มีอยู่ในระบบแล้ว หากต้องการแก้ไข กรุณาไปที่หน้าสต็อก', 'warning')
                active_tab = 'tire'
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)
            except Exception as e:
                flash(f'เกิดข้อผิดพลาดในการเพิ่มยาง: {e}', 'danger')
                active_tab = 'tire'
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)

        elif submit_type == 'add_wheel':
            brand = request.form['brand'].strip()
            model = request.form['model'].strip()
            diameter = request.form['diameter'] 
            pcd = request.form['pcd'].strip()
            width = request.form['width'] 
            quantity = request.form['quantity'] 
            
            cost = request.form.get('cost') 

            retail_price = request.form['retail_price'] 
            
            et = request.form.get('et')
            color = request.form.get('color', '').strip()
            cost_online = request.form.get('cost_online')
            wholesale_price1 = request.form.get('wholesale_price1')
            wholesale_price2 = request.form.get('wholesale_price2')
            image_file = request.files.get('image_file')

            if not brand or not model or not pcd or not diameter or not width or not quantity or not retail_price:
                flash('กรุณากรอกข้อมูลแม็กให้ครบถ้วนในช่องที่มีเครื่องหมาย *', 'danger')
                active_tab = 'wheel' 
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions) 
            
            try:
                diameter = float(diameter)
                width = float(width)
                quantity = int(quantity)
                retail_price = float(retail_price)

                cost = float(cost) if cost and cost.strip() else None

                et = int(et) if et and et.strip() else None
                cost_online = float(cost_online) if cost_online and cost_online.strip() else None
                wholesale_price1 = float(wholesale_price1) if wholesale_price1 and wholesale_price1.strip() else None
                wholesale_price2 = float(wholesale_price2) if wholesale_price2 and wholesale_price2.strip() else None

                filename = None
                if image_file and allowed_image_file(image_file.filename):
                    original_filename = secure_filename(image_file.filename)
                    name, ext = os.path.splitext(original_filename)
                    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                    filename = f"{name}_{timestamp}{ext}"
                    image_path = os.path.join(app.config['WHEEL_IMAGE_FOLDER'], filename)
                    image_file.save(image_path)
                elif image_file and not allowed_image_file(image_file.filename):
                    flash('ชนิดไฟล์รูปภาพไม่ถูกต้อง อนุญาตเฉพาะ .png, .jpg, .jpeg, .gif เท่านั้น', 'danger')
                    active_tab = 'wheel' 
                    return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)


                database.add_wheel(conn, brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, filename)
                flash('เพิ่มแม็กใหม่สำเร็จ!', 'success')
                return redirect(url_for('add_item', tab='wheel'))

            except ValueError:
                flash('ข้อมูลตัวเลขไม่ถูกต้อง กรุณาตรวจสอบ', 'danger')
                active_tab = 'wheel' 
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)
            except sqlite3.IntegrityError:
                flash(f'แม็กยี่ห้อ {brand} ลาย {model} ขอบ {diameter} รู {pcd} กว้าง {width} มีอยู่ในระบบแล้ว หากต้องการแก้ไข กรุณาไปที่หน้าสต็อก', 'warning')
                active_tab = 'wheel' 
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)
            except Exception as e:
                flash(f'เกิดข้อผิดพลาดในการเพิ่มแม็ก: {e}', 'danger')
                active_tab = 'wheel' 
                return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)
    
    return render_template('add_item.html', form_data=form_data, active_tab=active_tab, current_year=current_year, all_promotions=all_promotions)


@app.route('/edit_tire/<int:tire_id>', methods=('GET', 'POST'))
def edit_tire(tire_id):
    conn = get_db()
    tire = database.get_tire(conn, tire_id) 
    current_year = get_bkk_time().year 

    if tire is None:
        flash('ไม่พบยางที่ระบุ', 'danger')
        return redirect(url_for('index', tab='tires'))

    all_promotions = database.get_all_promotions(conn, include_inactive=True) 

    if request.method == 'POST':
        brand = request.form['brand'].strip()
        model = request.form['model'].strip()
        size = request.form['size'].strip()
        
        cost_sc = request.form.get('cost_sc') 
        price_per_item = request.form['price_per_item'] 
        
        cost_dunlop = request.form.get('cost_dunlop')
        cost_online = request.form.get('cost_online')
        wholesale_price1 = request.form.get('wholesale_price1')
        wholesale_price2 = request.form.get('wholesale_price2')
        
        promotion_id = request.form.get('promotion_id')
        if promotion_id == 'none' or not promotion_id:
            promotion_id_db = None
        else:
            promotion_id_db = int(promotion_id)

        year_of_manufacture = request.form.get('year_of_manufacture', '').strip() 

        if not brand or not model or not size or not str(price_per_item): 
            flash('กรุณากรอกข้อมูลยางให้ครบถ้วนในช่องที่มีเครื่องหมาย *', 'danger')
        else:
            try:
                price_per_item = float(price_per_item) 

                cost_sc = float(cost_sc) if cost_sc and cost_sc.strip() else None
                cost_dunlop = float(cost_dunlop) if cost_dunlop and cost_dunlop.strip() else None
                cost_online = float(cost_online) if cost_online and cost_online.strip() else None
                wholesale_price1 = float(wholesale_price1) if wholesale_price1 and wholesale_price1.strip() else None
                wholesale_price2 = float(wholesale_price2) if wholesale_price2 and wholesale_price2.strip() else None
                
                # year_of_manufacture is TEXT in DB, so keep as string.
                year_of_manufacture_db = year_of_manufacture if year_of_manufacture else None


                database.update_tire(conn, tire_id, brand, model, size, cost_sc, cost_dunlop, cost_online, 
                                     wholesale_price1, wholesale_price2, price_per_item, 
                                     promotion_id_db, 
                                     year_of_manufacture_db) 
                flash('แก้ไขข้อมูลยางสำเร็จ!', 'success')
                return redirect(url_for('index', tab='tires'))
            except ValueError:
                flash('ข้อมูลตัวเลขไม่ถูกต้อง กรุณาตรวจสอบ', 'danger')
            except sqlite3.IntegrityError:
                flash(f'ยางยี่ห้อ {brand} รุ่น {model} เบอร์ {size} นี้มีอยู่ในระบบแล้วภายใต้ ID อื่น โปรดตรวจสอบ', 'warning')
            except Exception as e:
                flash(f'เกิดข้อผิดพลาดในการแก้ไขข้อมูลยาง: {e}', 'danger')

    return render_template('edit_tire.html', tire=tire, current_year=current_year, all_promotions=all_promotions)

@app.route('/delete_tire/<int:tire_id>', methods=('POST',))
def delete_tire(tire_id):
    conn = get_db()
    tire = database.get_tire(conn, tire_id)

    if tire is None:
        flash('ไม่พบยางที่ระบุ', 'danger') 
    elif tire['quantity'] > 0:
        flash('ไม่สามารถลบยางได้เนื่องจากยังมีสต็อกเหลืออยู่. กรุณาปรับสต็อกให้เป็น 0 ก่อน.', 'danger')
        return redirect(url_for('index', tab='tires')) 
    else: 
        try:
            database.delete_tire(conn, tire_id)
            flash('ลบยางสำเร็จ!', 'success')
        except Exception as e:
            flash(f'เกิดข้อผิดพลาดในการลบยาง: {e}', 'danger')
    
    return redirect(url_for('index', tab='tires'))

# --- Wheel Routes ---
@app.route('/wheel_detail/<int:wheel_id>')
def wheel_detail(wheel_id):
    conn = get_db()
    wheel = database.get_wheel(conn, wheel_id)
    fitments = database.get_wheel_fitments(conn, wheel_id)
    current_year = get_bkk_time().year 

    if wheel is None:
        flash('ไม่พบแม็กที่ระบุ', 'danger')
        return redirect(url_for('index', tab='wheels'))
    
    return render_template('wheel_detail.html', wheel=wheel, fitments=fitments, current_year=current_year)


@app.route('/edit_wheel/<int:wheel_id>', methods=('GET', 'POST'))
def edit_wheel(wheel_id):
    conn = get_db()
    wheel = database.get_wheel(conn, wheel_id)
    current_year = get_bkk_time().year 

    if wheel is None:
        flash('ไม่พบแม็กที่ระบุ', 'danger')
        return redirect(url_for('index', tab='wheels'))

    if request.method == 'POST':
        brand = request.form['brand'].strip()
        model = request.form['model'].strip()
        diameter = float(request.form['diameter'])
        pcd = request.form['pcd'].strip()
        width = float(request.form['width'])
        et = request.form.get('et')
        color = request.form.get('color', '').strip()
        cost = request.form.get('cost') 
        cost_online = request.form.get('cost_online')
        wholesale_price1 = request.form.get('wholesale_price1')
        wholesale_price2 = request.form.get('wholesale_price2')
        retail_price = float(request.form['retail_price'])
        image_file = request.files.get('image_file')

        if not brand or not model or not pcd or not str(diameter) or not str(width) or not str(retail_price): 
            flash('กรุณากรอกข้อมูลแม็กให้ครบถ้วนในช่องที่มีเครื่องหมาย *', 'danger')
        else:
            try:
                et = int(et) if et else None
                cost_online = float(cost_online) if cost_online else None
                wholesale_price1 = float(wholesale_price1) if wholesale_price1 else None
                wholesale_price2 = float(wholesale_price2) if wholesale_price2 else None
                cost = float(cost) if cost and cost.strip() else None 

                current_image_filename = wheel['image_filename'] 
                if image_file and allowed_image_file(image_file.filename):
                    if current_image_filename:
                        old_image_path = os.path.join(app.config['WHEEL_IMAGE_FOLDER'], current_image_filename)
                        if os.path.exists(old_image_path):
                            os.remove(old_image_path)
                    
                    original_filename = secure_filename(image_file.filename)
                    name, ext = os.path.splitext(original_filename)
                    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                    filename = f"{name}_{timestamp}{ext}"
                    image_path = os.path.join(app.config['WHEEL_IMAGE_FOLDER'], new_filename)
                    image_file.save(image_path)
                    current_image_filename = new_filename 
                elif image_file and not allowed_image_file(image_file.filename):
                    flash('ชนิดไฟล์รูปภาพไม่ถูกต้อง อนุญาตเฉพาะ .png, .jpg, .jpeg, .gif เท่านั้น', 'danger')
                    return render_template('edit_wheel.html', wheel=wheel, current_year=current_year)


                database.update_wheel(conn, wheel_id, brand, model, diameter, pcd, width, et, color, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, current_image_filename)
                flash('แก้ไขข้อมูลแม็กสำเร็จ!', 'success')
                return redirect(url_for('wheel_detail', wheel_id=wheel_id))
            except ValueError:
                flash('ข้อมูลตัวเลขไม่ถูกต้อง กรุณาตรวจสอบ', 'danger')
            except sqlite3.IntegrityError:
                flash(f'แม็กยี่ห้อ {brand} ลาย {model} ขอบ {diameter} รู {pcd} กว้าง {width} นี้มีอยู่ในระบบแล้วภายใต้ ID อื่น โปรดตรวจสอบ', 'warning')
            except Exception as e:
                flash(f'เกิดข้อผิดพลาดในการแก้ไขข้อมูลแม็ก: {e}', 'danger')

    return render_template('edit_wheel.html', wheel=wheel, current_year=current_year)

@app.route('/delete_wheel/<int:wheel_id>', methods=('POST',))
def delete_wheel(wheel_id):
    conn = get_db()
    wheel = database.get_wheel(conn, wheel_id)

    if wheel is None:
        flash('ไม่พบแม็กที่ระบุ', 'danger')
    elif wheel['quantity'] > 0: 
        flash('ไม่สามารถลบแม็กได้เนื่องจากยังมีสต็อกเหลืออยู่. กรุณาปรับสต็อกให้เป็น 0 ก่อน.', 'danger')
        return redirect(url_for('index', tab='wheels')) 
    else:
        try:
            if wheel['image_filename']:
                image_path = os.path.join(app.config['WHEEL_IMAGE_FOLDER'], wheel['image_filename']) 
                if os.path.exists(image_path):
                    os.remove(image_path)
            
            database.delete_wheel(conn, wheel_id)
            flash('ลบแม็กสำเร็จ!', 'success')
        except Exception as e:
            flash(f'เกิดข้อผิดพลาดในการลบแม็ก: {e}', 'danger')
    
    return redirect(url_for('index', tab='wheels'))

@app.route('/add_fitment/<int:wheel_id>', methods=('POST',))
def add_fitment(wheel_id):
    conn = get_db()
    brand = request.form['brand'].strip()
    model = request.form['model'].strip()
    year_start = request.form['year_start'].strip()
    year_end = request.form.get('year_end', '').strip()

    if not brand or not model or not year_start:
        flash('กรุณากรอกข้อมูลการรองรับรถยนต์ให้ครบถ้วน', 'danger')
    else:
        try:
            year_start = int(year_start)
            year_end = int(year_end) if year_end else None

            if year_end and year_end < year_start:
                flash('ปีสิ้นสุดต้องไม่น้อยกว่าปีเริ่มต้น', 'danger')
            else:
                database.add_wheel_fitment(conn, wheel_id, brand, model, year_start, year_end)
                flash('เพิ่มข้อมูลการรองรับสำเร็จ!', 'success')
        except ValueError:
            flash('ข้อมูลปีไม่ถูกต้อง กรุณาตรวจสอบ', 'danger')
        except Exception as e:
            flash(f'เกิดข้อผิดพลาดในการเพิ่มข้อมูลการรองรับ: {e}', 'danger')
    
    return redirect(url_for('wheel_detail', wheel_id=wheel_id))

@app.route('/delete_fitment/<int:fitment_id>/<int:wheel_id>', methods=('POST',))
def delete_fitment(fitment_id, wheel_id):
    conn = get_db()
    try:
        database.delete_wheel_fitment(conn, fitment_id)
        flash('ลบข้อมูลการรองรับสำเร็จ!', 'success')
    except Exception as e:
        flash(f'เกิดข้อผิดพลาดในการลบข้อมูลการรองรับ: {e}', 'danger')
    
    return redirect(url_for('wheel_detail', wheel_id=wheel_id))


# --- Stock Movement Routes ---
@app.route('/stock_movement', methods=('GET', 'POST'))
def stock_movement():
    conn = get_db()
    
    tires = database.get_all_tires(conn)
    wheels = database.get_all_wheels(conn)
    active_tab = request.args.get('tab', 'tire_movements') 

    cursor_tire_movements = conn.execute("SELECT tm.*, t.brand, t.model, t.size FROM tire_movements tm JOIN tires t ON tm.tire_id = t.id ORDER BY tm.timestamp DESC LIMIT 50")
    tire_movements_history = cursor_tire_movements.fetchall()

    cursor_wheel_movements = conn.execute("SELECT wm.*, w.brand, w.model, w.diameter FROM wheel_movements wm JOIN wheels w ON wm.wheel_id = w.id ORDER BY wm.timestamp DESC LIMIT 50")
    wheel_movements_history = cursor_wheel_movements.fetchall()


    if request.method == 'POST':
        submit_type = request.form.get('submit_type')
        active_tab_on_error = 'tire_movements' if submit_type == 'tire_movement' else 'wheel_movements'

        if submit_type == 'tire_movement':
            item_id_key = 'tire_id'
            quantity_form_key = 'quantity' 
        elif submit_type == 'wheel_movement':
            item_id_key = 'wheel_id'
            quantity_form_key = 'quantity' 
        else:
            flash('ประเภทการส่งฟอร์มไม่ถูกต้อง', 'danger')
            return redirect(url_for('stock_movement'))
        
        if quantity_form_key not in request.form or not request.form[quantity_form_key].strip():
            flash('กรุณากรอกจำนวนที่เปลี่ยนแปลงให้ถูกต้อง', 'danger')
            return redirect(url_for('stock_movement', tab=active_tab_on_error))
        
        try:
            item_id = request.form[item_id_key]
            move_type = request.form['type']
            quantity_change = int(request.form[quantity_form_key]) 
            notes = request.form.get('notes', '').strip()

            if quantity_change <= 0:
                flash('จำนวนที่เปลี่ยนแปลงต้องมากกว่า 0', 'danger')
                return redirect(url_for('stock_movement', tab=active_tab_on_error))
            
            if submit_type == 'tire_movement':
                tire_id = int(item_id)
                current_tire = database.get_tire(conn, tire_id)
                if current_tire is None:
                    flash('ไม่พบยางที่ระบุ', 'danger')
                    return redirect(url_for('stock_movement', tab=active_tab_on_error))
                
                new_quantity = current_tire['quantity']
                if move_type == 'IN':
                    new_quantity += quantity_change
                elif move_type == 'OUT':
                    if new_quantity < quantity_change:
                        flash(f'สต็อกยางไม่พอสำหรับการจ่ายออก. มีเพียง {new_quantity} เส้น.', 'danger')
                        return redirect(url_for('stock_movement', tab=active_tab_on_error))
                    new_quantity -= quantity_change
                
                database.update_tire_quantity(conn, tire_id, new_quantity)
                database.add_tire_movement(conn, tire_id, move_type, quantity_change, new_quantity, notes)
                flash(f'บันทึกการเคลื่อนไหวสต็อกยางสำเร็จ! คงเหลือ: {new_quantity} เส้น', 'success')
                return redirect(url_for('stock_movement', tab='tire_movements'))

            elif submit_type == 'wheel_movement':
                wheel_id = int(item_id)
                current_wheel = database.get_wheel(conn, wheel_id)
                if current_wheel is None:
                    flash('ไม่พบแม็กที่ระบุ', 'danger')
                    return redirect(url_for('stock_movement', tab=active_tab_on_error))
                
                new_quantity = current_wheel['quantity']
                if move_type == 'IN':
                    new_quantity += quantity_change
                elif move_type == 'OUT':
                    if new_quantity < quantity_change:
                        flash(f'สต็อกแม็กไม่พอสำหรับการจ่ายออก. มีเพียง {new_quantity} วง.', 'danger')
                        return redirect(url_for('stock_movement', tab=active_tab_on_error))
                    new_quantity -= quantity_change
                
                database.update_wheel_quantity(conn, wheel_id, new_quantity)
                database.add_wheel_movement(conn, wheel_id, move_type, quantity_change, new_quantity, notes)
                flash(f'บันทึกการเคลื่อนไหวสต็อกแม็กสำเร็จ! คงเหลือ: {new_quantity} วง', 'success')
                return redirect(url_for('stock_movement', tab='wheel_movements'))

        except ValueError:
            flash('ข้อมูลตัวเลขไม่ถูกต้อง กรุณาตรวจสอบ', 'danger')
            return redirect(url_for('stock_movement', tab=active_tab_on_error))
        except Exception as e:
            flash(f'เกิดข้อผิดพลาดในการบันทึกการเคลื่อนไหวสต็อก: {e}', 'danger')
            return redirect(url_for('stock_movement', tab=active_tab_on_error))
    
    return render_template('stock_movement.html', 
                           tires=tires, 
                           wheels=wheels, 
                           active_tab=active_tab,
                           tire_movements=tire_movements_history, 
                           wheel_movements=wheel_movements_history)

# --- Import/Export Routes ---
@app.route('/export_import', methods=('GET', 'POST'))
def export_import():
    active_tab = request.args.get('tab', 'tires_excel')
    return render_template('export_import.html', active_tab=active_tab)

@app.route('/export_tires_action')
def export_tires_action():
    conn = get_db()
    tires = database.get_all_tires(conn) 
    
    if not tires:
        flash('ไม่มีข้อมูลยางให้ส่งออก', 'warning')
        return redirect(url_for('export_import', tab='tires_excel'))

    data = []
    for tire in tires:
        data.append({
            'ID': tire['id'],
            'ยี่ห้อ': tire['brand'],
            'รุ่นยาง': tire['model'],
            'เบอร์ยาง': tire['size'],
            'สต็อก': tire['quantity'],
            'ทุน SC': tire['cost_sc'],
            'ทุน Dunlop': tire['cost_dunlop'],
            'ทุน Online': tire['cost_online'],
            'ราคาขายส่ง 1': tire['wholesale_price1'],
            'ราคาขายส่ง 2': tire['wholesale_price2'],
            'ราคาต่อเส้น': tire['price_per_item'], 
            'ID โปรโมชัน': tire['promotion_id'], 
            'ชื่อโปรโมชัน': tire['promo_name'], 
            'ประเภทโปรโมชัน': tire['promo_type'], 
            'ค่าโปรโมชัน Value1': tire['promo_value1'],
            'ค่าโปรโมชัน Value2': tire['promo_value2'],
            'รายละเอียดโปรโมชัน': tire['display_promo_description_text'], 
            'ราคาโปรโมชันคำนวณ(เส้น)': tire['display_promo_price_per_item'], 
            'ราคาโปรโมชันคำนวณ(4เส้น)': tire['display_price_for_4'], 
            'ปีผลิต': tire['year_of_manufacture'], # Use directly, it's already string formatted by database.py
        })
    
    df = pd.DataFrame(data)
    
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    df.to_excel(writer, index=False, sheet_name='Tires Stock')
    writer.close()
    output.seek(0)
    
    return send_file(output, download_name='tire_stock.xlsx', as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/import_tires_action', methods=('POST',))
def import_tires_action():
    if 'file' not in request.files:
        flash('ไม่พบไฟล์ที่อัปโหลด', 'danger')
        return redirect(url_for('export_import', tab='tires_excel'))
    
    file = request.files['file']
    
    if file.filename == '':
        flash('ไม่ได้เลือกไฟล์', 'danger')
        return redirect(url_for('export_import', tab='tires_excel'))
    
    if file and allowed_excel_file(file.filename):
        try:
            df = pd.read_excel(file)
            conn = get_db()
            imported_count = 0
            updated_count = 0
            error_rows = []

            expected_tire_cols = [
                'ยี่ห้อ', 'รุ่นยาง', 'เบอร์ยาง', 'สต็อก', 'ทุน SC', 'ทุน Dunlop', 'ทุน Online',
                'ราคาขายส่ง 1', 'ราคาขายส่ง 2', 'ราคาต่อเส้น', 'ID โปรโมชัน', 'ปีผลิต' 
            ]
            
            if not all(col in df.columns for col in expected_tire_cols):
                missing_cols = [col for col in expected_tire_cols if col not in df.columns]
                flash(f'ไฟล์ Excel ขาดคอลัมน์ที่จำเป็น: {", ".join(missing_cols)}. โปรดดาวน์โหลดไฟล์ตัวอย่างเพื่อดูรูปแบบที่ถูกต้อง.', 'danger')
                return redirect(url_for('export_import', tab='tires_excel'))

            for index, row in df.iterrows():
                try:
                    brand = str(row.get('ยี่ห้อ', '')).strip()
                    model = str(row.get('รุ่นยาง', '')).strip()
                    size = str(row.get('เบอร์ยาง', '')).strip()
                    
                    if not brand or not model or not size:
                        raise ValueError("ข้อมูล 'ยี่ห้อ', 'รุ่นยาง', หรือ 'เบอร์ยาง' ไม่สามารถเว้นว่างได้")

                    quantity = int(row['สต็อก']) if pd.notna(row['สต็อก']) else 0
                    price_per_item = float(row['ราคาต่อเส้น']) if pd.notna(row['ราคาต่อเส้น']) else 0.0 

                    cost_sc = float(row['ทุน SC']) if pd.notna(row['ทุน SC']) else None 
                    cost_dunlop = float(row['ทุน Dunlop']) if pd.notna(row['ทุน Dunlop']) else None
                    cost_online = float(row['ทุน Online']) if pd.notna(row['ทุน Online']) else None
                    wholesale_price1 = float(row['ราคาขายส่ง 1']) if pd.notna(row['ราคาขายส่ง 1']) else None
                    wholesale_price2 = float(row['ราคาขายส่ง 2']) if pd.notna(row['ราคาขายส่ง 2']) else None
                    
                    promotion_id = int(row.get('ID โปรโมชัน')) if pd.notna(row.get('ID โปรโมชัน')) else None
                    
                    year_of_manufacture = str(row.get('ปีผลิต')) if pd.notna(row.get('ปีผลิต')) else None # Keep as string
                    
                    existing_tire = conn.execute("SELECT id, quantity FROM tires WHERE brand = ? AND model = ? AND size = ?", (brand, model, size)).fetchone()

                    if existing_tire:
                        tire_id = existing_tire['id']
                        database.update_tire_import(conn, tire_id, brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, 
                                                    promotion_id, year_of_manufacture)
                        updated_count += 1
                        
                        old_quantity = existing_tire['quantity']
                        if quantity != old_quantity:
                            movement_type = 'IN' if quantity > old_quantity else 'OUT'
                            quantity_change_diff = abs(quantity - old_quantity)
                            database.add_tire_movement(conn, tire_id, movement_type, quantity_change_diff, quantity, "Import from Excel (Qty Update)")
                        
                    else:
                        new_tire_id = database.add_tire_import(conn, brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, 
                                                               promotion_id, year_of_manufacture)
                        database.add_tire_movement(conn, new_tire_id, 'IN', quantity, quantity, "Import from Excel (initial stock)")
                        imported_count += 1
                except Exception as row_e:
                    error_rows.append(f"แถวที่ {index + 2}: {row_e} - {row.to_dict()}")
            
            conn.commit()
            
            message = f'นำเข้าข้อมูลยางสำเร็จ: เพิ่มใหม่ {imported_count} รายการ, อัปเดต {updated_count} รายการ.'
            if error_rows:
                message += f' พบข้อผิดพลาดใน {len(error_rows)} แถว: {"; ".join(error_rows[:3])}{"..." if len(error_rows) > 3 else ""}'
                flash(message, 'warning')
            else:
                flash(message, 'success')
            
            return redirect(url_for('export_import', tab='tires_excel'))

        except Exception as e:
            flash(f'เกิดข้อผิดพลาดในการนำเข้าไฟล์ Excel ของยาง: {e}', 'danger')
            if 'db' in g and g.db is not None:
                g.db.rollback()
            return redirect(url_for('export_import', tab='tires_excel'))
    else:
        flash('ชนิดไฟล์ไม่ถูกต้อง อนุญาตเฉพาะ .xlsx และ .xls เท่านั้น', 'danger')
        return redirect(url_for('export_import', tab='tires_excel'))

@app.route('/export_wheels_action')
def export_wheels_action():
    conn = get_db()
    wheels = database.get_all_wheels(conn)
    
    if not wheels:
        flash('ไม่มีข้อมูลแม็กให้ส่งออก', 'warning')
        return redirect(url_for('export_import', tab='wheels_excel'))

    data = []
    for wheel in wheels:
        data.append({
            'ID': wheel['id'],
            'ยี่ห้อ': wheel['brand'],
            'ลาย': wheel['model'],
            'ขอบ': wheel['diameter'],
            'รู': wheel['pcd'],
            'กว้าง': wheel['width'],
            'ET': wheel['et'],
            'สี': wheel['color'],
            'สต็อก': wheel['quantity'],
            'ทุน': wheel['cost'],
            'ทุน Online': wheel['cost_online'],
            'ราคาขายส่ง 1': wheel['wholesale_price1'],
            'ราคาขายส่ง 2': wheel['wholesale_price2'],
            'ราคาปลีก': wheel['retail_price'],
            'ไฟล์รูปภาพ': wheel['image_filename']
        })
    
    df = pd.DataFrame(data)
    
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    df.to_excel(writer, index=False, sheet_name='Wheels Stock')
    writer.close()
    output.seek(0)
    
    return send_file(output, download_name='wheel_stock.xlsx', as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/import_wheels_action', methods=('POST',))
def import_wheels_action():
    if 'file' not in request.files:
        flash('ไม่พบไฟล์ที่อัปโหลด', 'danger')
        return redirect(url_for('export_import', tab='wheels_excel'))
    
    file = request.files['file']
    
    if file.filename == '':
        flash('ไม่ได้เลือกไฟล์', 'danger')
        return redirect(url_for('export_import', tab='wheels_excel'))
    
    if file and allowed_excel_file(file.filename):
        try:
            df = pd.read_excel(file)
            conn = get_db()
            imported_count = 0
            updated_count = 0
            error_rows = []

            expected_wheel_cols = [
                'ยี่ห้อ', 'ลาย', 'ขอบ', 'รู', 'กว้าง', 'ET', 'สี', 'สต็อก',
                'ทุน', 'ทุน Online', 'ราคาขายส่ง 1', 'ราคาขายส่ง 2', 'ราคาปลีก', 'ไฟล์รูปภาพ'
            ]
            if not all(col in df.columns for col in expected_wheel_cols):
                missing_cols = [col for col in expected_wheel_cols if col not in df.columns]
                flash(f'ไฟล์ Excel ขาดคอลัมน์ที่จำเป็น: {", ".join(missing_cols)}. โปรดดาวน์โหลดไฟล์ตัวอย่างเพื่อดูรูปแบบที่ถูกต้อง.', 'danger')
                return redirect(url_for('export_import', tab='wheels_excel'))


            for index, row in df.iterrows():
                try:
                    brand = str(row.get('ยี่ห้อ', '')).strip()
                    model = str(row.get('ลาย', '')).strip()
                    pcd = str(row.get('รู', '')).strip()

                    if not brand or not model or not pcd:
                            raise ValueError("ข้อมูล 'ยี่ห้อ', 'ลาย', หรือ 'รู' ไม่สามารถเว้นว่างได้")

                    diameter = float(row['ขอบ']) if pd.notna(row['ขอบ']) else 0.0
                    width = float(row['กว้าง']) if pd.notna(row['กว้าง']) else 0.0
                    quantity = int(row['สต็อก']) if pd.notna(row['สต็อก']) else 0
                    cost = float(row['ทุน']) if pd.notna(row['ทุน']) else None 
                    retail_price = float(row['ราคาขายปลีก']) if pd.notna(row['ราคาขายปลีก']) else 0.0

                    et = int(row['ET']) if pd.notna(row['ET']) else None
                    color = str(row['สี']).strip() if pd.notna(row['สี']) else None
                    cost_online = float(row['ทุน Online']) if pd.notna(row['ทุน Online']) else None
                    wholesale_price1 = float(row['ราคาขายส่ง 1']) if pd.notna(row['ราคาขายส่ง 1']) else None
                    wholesale_price2 = float(row['ราคาขายส่ง 2']) if pd.notna(row['ราคาขายส่ง 2']) else None
                    image_filename = str(row['ไฟล์รูปภาพ']).strip() if pd.notna(row['ไฟล์รูปภาพ']) else None
                    
                    existing_wheel = conn.execute("SELECT id, quantity FROM wheels WHERE brand = ? AND model = ? AND diameter = ? AND pcd = ? AND width = ? AND (et IS ? OR et = ?) AND (color IS ? OR color = ?)", 
                                                 (brand, model, diameter, pcd, width, et, et, color, color)).fetchone()

                    if existing_wheel:
                        wheel_id = existing_wheel['id']
                        database.update_wheel_import(conn, wheel_id, brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename)
                        updated_count += 1
                        
                        old_quantity = existing_wheel['quantity']
                        if quantity != old_quantity:
                            movement_type = 'IN' if quantity > old_quantity else 'OUT'
                            quantity_change_diff = abs(quantity - old_quantity)
                            database.add_wheel_movement(conn, wheel_id, movement_type, quantity_change_diff, quantity, "Import from Excel (Qty Update)")
                    else:
                        new_wheel_id = database.add_wheel_import(conn, brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename)
                        database.add_wheel_movement(conn, new_wheel_id, 'IN', quantity, quantity, "Import from Excel (initial stock)")
                        imported_count += 1
                except Exception as row_e:
                    error_rows.append(f"แถวที่ {index + 2}: {row_e} - {row.to_dict()}")
            
            conn.commit()
            
            message = f'นำเข้าข้อมูลแม็กสำเร็จ: เพิ่มใหม่ {imported_count} รายการ, อัปเดต {updated_count} รายการ.'
            if error_rows:
                message += f' พบข้อผิดพลาดใน {len(error_rows)} แถว: {"; ".join(error_rows[:3])}{"..." if len(error_rows) > 3 else ""}'
                flash(message, 'warning')
            else:
                flash(message, 'success')
            
            return redirect(url_for('export_import', tab='wheels_excel'))

        except Exception as e:
            flash(f'เกิดข้อผิดพลาดในการนำเข้าไฟล์ Excel ของแม็ก: {e}', 'danger')
            if 'db' in g and g.db is not None:
                g.db.rollback()
            return redirect(url_for('export_import', tab='wheels_excel'))
    else:
        flash('ชนิดไฟล์ไม่ถูกต้อง อนุญาตเฉพาะ .xlsx และ .xls เท่านั้น', 'danger')
        return redirect(url_for('export_import', tab='wheels_excel'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000)) # บรรทัดนี้สำคัญมาก
    app.run(host='0.0.0.0', port=port, debug=True)