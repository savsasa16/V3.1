import sqlite3
from datetime import datetime
import pytz
import os

def get_db_connection():
    # Connect to the database file within the persistent disk's mount path
    db_path = os.environ.get('DATABASE_PATH', '/var/data/inventory.db') 

    # Ensure the directory exists before connecting
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def get_bkk_time():
    bkk_tz = pytz.timezone('Asia/Bangkok')
    return datetime.now(bkk_tz)

def get_db_connection():
    conn = sqlite3.connect('inventory.db')
    conn.row_factory = sqlite3.Row # This allows accessing columns by name (e.g., row['column_name'])
    return conn

def init_db(conn):
    cursor = conn.cursor()

    # --- Schema Migration for 'tires' table (Updated for year_of_manufacture TEXT and robust migration) ---
    try:
        cursor.execute("PRAGMA foreign_keys = OFF;") # Temporarily disable FK checks for migration
        conn.commit()

        # Check if 'tires' table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tires';")
        tires_table_exists = cursor.fetchone()

        needs_migration = False
        if tires_table_exists:
            cursor.execute("PRAGMA table_info(tires);")
            columns = [col[1] for col in cursor.fetchall()]

            # Determine if 'year_of_manufacture' needs type change or if new columns are missing
            if 'year_of_manufacture' in columns:
                # Get the actual type of data stored in year_of_manufacture
                cursor.execute("SELECT year_of_manufacture FROM tires WHERE year_of_manufacture IS NOT NULL LIMIT 1;")
                test_val_row = cursor.fetchone()
                
                # If it's not TEXT (e.g., 'integer' or 'real' from old schema)
                if test_val_row and test_val_row['year_of_manufacture'] is not None:
                    # Check its Python type, if it's int or float, it needs conversion
                    if isinstance(test_val_row['year_of_manufacture'], (int, float)):
                        print("Migrating 'tires' table: 'year_of_manufacture' type needs to be TEXT to preserve leading zeros.")
                        needs_migration = True
                    # Else, if it's already a string, no type migration needed for this column directly
            else: # 'year_of_manufacture' column itself might be missing (older schema)
                print("Migrating 'tires' table: 'year_of_manufacture' column missing, will add as TEXT.")
                needs_migration = True

            # Check for other new columns if they were added in an intermediate step and might be missing
            # E.g., if 'promotion_id' was added via ALTER TABLE and wasn't part of the initial CREATE TABLE
            if 'promotion_id' not in columns:
                 print("Migrating 'tires' table: 'promotion_id' column missing, will add.")
                 needs_migration = True
            if 'price_per_item' not in columns and 'retail_price' in columns:
                 print("Migrating 'tires' table: 'retail_price' needs to be renamed to 'price_per_item'.")
                 needs_migration = True
            
        # else: tires_table_exists is False, so table will be created below, no migration needed here.

    except sqlite3.OperationalError as e:
        print(f"OperationalError during tires migration check: {e}. Assuming tables need creation.")
        needs_migration = False 
        
    if needs_migration:
        print("Performing schema migration for 'tires' table (copying data)...")
        try:
            # 1. Rename old table
            cursor.execute("ALTER TABLE tires RENAME TO old_tires;")
            conn.commit()

            # 2. Create new table with correct schema (year_of_manufacture TEXT)
            cursor.execute("""
                CREATE TABLE tires ( 
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    brand TEXT NOT NULL,
                    model TEXT NOT NULL,
                    size TEXT NOT NULL,
                    quantity INTEGER DEFAULT 0,
                    cost_sc REAL NULL, 
                    cost_dunlop REAL NULL,
                    cost_online REAL NULL,
                    wholesale_price1 REAL NULL,
                    wholesale_price2 REAL NULL,
                    price_per_item REAL NOT NULL,   
                    promotion_id INTEGER NULL,      
                    year_of_manufacture TEXT NULL,  -- <<< IMPORTANT: Now TEXT for flexible input
                    UNIQUE(brand, model, size),
                    FOREIGN KEY (promotion_id) REFERENCES promotions(id) ON DELETE SET NULL
                );
            """)
            conn.commit()

            # 3. Copy data from old table to new table
            cursor.execute("PRAGMA table_info(old_tires);")
            old_tires_col_names = [col[1] for col in cursor.fetchall()]
            
            insert_cols_list = []
            select_cols_list = []

            # Map old columns to new columns
            # 'id' is special, let SQLite handle AUTOINCREMENT if not present in old table
            # If copying 'id', make sure to copy all columns. If not, omit 'id' and let new table generate.
            
            # Common columns
            insert_cols_list.extend(['brand', 'model', 'size', 'quantity'])
            select_cols_list.extend(['brand', 'model', 'size', 'quantity'])

            # Optional cost columns
            insert_cols_list.append('cost_sc'); select_cols_list.append('cost_sc' if 'cost_sc' in old_tires_col_names else 'NULL')
            insert_cols_list.append('cost_dunlop'); select_cols_list.append('cost_dunlop' if 'cost_dunlop' in old_tires_col_names else 'NULL')
            insert_cols_list.append('cost_online'); select_cols_list.append('cost_online' if 'cost_online' in old_tires_col_names else 'NULL')
            insert_cols_list.append('wholesale_price1'); select_cols_list.append('wholesale_price1' if 'wholesale_price1' in old_tires_col_names else 'NULL')
            insert_cols_list.append('wholesale_price2'); select_cols_list.append('wholesale_price2' if 'wholesale_price2' in old_tires_col_names else 'NULL')
            
            # Price column: Handle rename from 'retail_price' to 'price_per_item'
            if 'price_per_item' in old_tires_col_names:
                insert_cols_list.append('price_per_item'); select_cols_list.append('price_per_item')
            elif 'retail_price' in old_tires_col_names:
                insert_cols_list.append('price_per_item'); select_cols_list.append('retail_price')
            else: # Default price if neither exists
                insert_cols_list.append('price_per_item'); select_cols_list.append('0.0')

            # promotion_id: new column, set to NULL for old data
            insert_cols_list.append('promotion_id'); select_cols_list.append('NULL') 

            # year_of_manufacture: Convert to TEXT, handle missing/NULL.
            # Convert float/int to string, then trim '.0' if present.
            if 'year_of_manufacture' in old_tires_col_names:
                insert_cols_list.append('year_of_manufacture')
                select_cols_list.append("""
                    CASE 
                        WHEN typeof(old_tires.year_of_manufacture) = 'real' AND old_tires.year_of_manufacture = CAST(old_tires.year_of_manufacture AS INTEGER) 
                        THEN CAST(CAST(old_tires.year_of_manufacture AS INTEGER) AS TEXT)
                        WHEN typeof(old_tires.year_of_manufacture) = 'integer'
                        THEN CAST(old_tires.year_of_manufacture AS TEXT)
                        ELSE old_tires.year_of_manufacture
                    END
                """)
            else:
                insert_cols_list.append('year_of_manufacture')
                select_cols_list.append("NULL")

            insert_sql = f"INSERT INTO tires ({', '.join(insert_cols_list)}) SELECT {', '.join(select_cols_list)} FROM old_tires;"
            cursor.execute(insert_sql)
            conn.commit()

            # 4. Drop old table
            cursor.execute("DROP TABLE old_tires;")
            conn.commit()
            print("Tires table migration complete.")
            
        except Exception as e:
            print(f"Error during tires table migration: {e}")
            print("Attempting to restore old_tires table if migration failed mid-way.")
            conn.rollback() 
            # Re-enable FK checks even on failure
            cursor.execute("PRAGMA foreign_keys = ON;")
            conn.commit()
            raise # Re-raise the exception to signal failure
    # --- End Schema Migration ---

    # Re-enable foreign key checks (important!)
    cursor.execute("PRAGMA foreign_keys = ON;")
    conn.commit()


    # Ensure promotions table is created (if not already done by migration)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS promotions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,       
            type TEXT NOT NULL,             
            value1 REAL NOT NULL,           
            value2 REAL NULL,               
            is_active BOOLEAN DEFAULT 1,    
            created_at TEXT NOT NULL
        );
    """)
    conn.commit()

    # Ensure other tables are created if they don't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wheels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand TEXT NOT NULL,
            model TEXT NOT NULL,
            diameter REAL NOT NULL,
            pcd TEXT NOT NULL,
            width REAL NOT NULL,
            et INTEGER NULL,
            color TEXT NULL,
            quantity INTEGER DEFAULT 0,
            cost REAL NULL, 
            cost_online REAL NULL,
            wholesale_price1 REAL NULL,
            wholesale_price2 REAL NULL,
            retail_price REAL NOT NULL, 
            image_filename TEXT NULL,
            UNIQUE(brand, model, diameter, pcd, width, et, color)
        );
    """)
    conn.commit()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tire_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tire_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            type TEXT NOT NULL, 
            quantity_change INTEGER NOT NULL,
            remaining_quantity INTEGER NOT NULL,
            notes TEXT,
            FOREIGN KEY (tire_id) REFERENCES tires(id)
        );
    """)
    conn.commit()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wheel_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wheel_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            type TEXT NOT NULL, 
            quantity_change INTEGER NOT NULL,
            remaining_quantity INTEGER NOT NULL,
            notes TEXT,
            FOREIGN KEY (wheel_id) REFERENCES wheels(id)
        );
    """)
    conn.commit()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wheel_fitments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wheel_id INTEGER NOT NULL,
            brand TEXT NOT NULL,
            model TEXT NOT NULL,
            year_start INTEGER NOT NULL,
            year_end INTEGER NULL,
            UNIQUE(wheel_id, brand, model, year_start, year_end),
            FOREIGN KEY (wheel_id) REFERENCES wheels(id) ON DELETE CASCADE
        );
    """)
    conn.commit()

# --- Promotion Functions ---
def add_promotion(conn, name, promo_type, value1, value2, is_active):
    created_at = get_bkk_time().isoformat()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO promotions (name, type, value1, value2, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (name, promo_type, value1, value2, is_active, created_at))
    conn.commit()
    return cursor.lastrowid

def get_promotion(conn, promo_id):
    cursor = conn.execute("SELECT * FROM promotions WHERE id = ?", (promo_id,))
    return cursor.fetchone()

def get_all_promotions(conn, include_inactive=False):
    sql_query = "SELECT * FROM promotions"
    params = []
    if not include_inactive:
        sql_query += " WHERE is_active = 1"
    sql_query += " ORDER BY name"
    cursor = conn.execute(sql_query, params)
    return cursor.fetchall()

def update_promotion(conn, promo_id, name, promo_type, value1, value2, is_active):
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE promotions SET
            name = ?,
            type = ?,
            value1 = ?,
            value2 = ?,
            is_active = ?
        WHERE id = ?
    """, (name, promo_type, value1, value2, is_active, promo_id))
    conn.commit()

def delete_promotion(conn, promo_id):
    conn.execute("UPDATE tires SET promotion_id = NULL WHERE promotion_id = ?", (promo_id,))
    conn.execute("DELETE FROM promotions WHERE id = ?", (promo_id,))
    conn.commit()

# --- Tire Functions (Modified) ---
def add_tire(conn, brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture):
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO tires (brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture))
    conn.commit()
    return cursor.lastrowid

def get_tire(conn, tire_id):
    cursor = conn.execute("""
        SELECT t.*, 
               p.name AS promo_name, 
               p.type AS promo_type, 
               p.value1 AS promo_value1, 
               p.value2 AS promo_value2,
               p.is_active AS promo_is_active
        FROM tires t
        LEFT JOIN promotions p ON t.promotion_id = p.id
        WHERE t.id = ?
    """, (tire_id,))
    tire = cursor.fetchone()
    
    if tire:
        tire_dict = dict(tire) 
        
        # Ensure year_of_manufacture is always a string and formatted if needed
        if 'year_of_manufacture' in tire_dict and tire_dict['year_of_manufacture'] is not None:
            # Convert float like 2025.0 to "2025"
            if isinstance(tire_dict['year_of_manufacture'], float) and tire_dict['year_of_manufacture'].is_integer():
                tire_dict['year_of_manufacture'] = str(int(tire_dict['year_of_manufacture']))
            else: # If it's already an int or string, just convert to string
                tire_dict['year_of_manufacture'] = str(tire_dict['year_of_manufacture'])
        else:
            tire_dict['year_of_manufacture'] = '' # Default to empty string if None


        tire_dict['display_promo_price_per_item'] = None 
        tire_dict['display_price_for_4'] = tire_dict['price_per_item'] * 4 if tire_dict['price_per_item'] is not None else None
        tire_dict['display_promo_description_text'] = None 

        if tire_dict['promotion_id'] is not None and tire_dict['promo_is_active'] == 1:
            promo_calc_result = calculate_tire_promo_prices(
                tire_dict['price_per_item'],
                tire_dict['promo_type'],
                tire_dict['promo_value1'],
                tire_dict['promo_value2']
            )
            tire_dict['display_promo_price_per_item'] = promo_calc_result['price_per_item_promo']
            tire_dict['display_price_for_4'] = promo_calc_result['price_for_4_promo']
            tire_dict['display_promo_description_text'] = promo_calc_result['promo_description_text']
        
        return tire_dict 
    return tire

def update_tire(conn, tire_id, brand, model, size, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture):
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE tires SET
            brand = ?,
            model = ?,
            size = ?,
            cost_sc = ?,
            cost_dunlop = ?,
            cost_online = ?,
            wholesale_price1 = ?,
            wholesale_price2 = ?,
            price_per_item = ?,
            promotion_id = ?,
            year_of_manufacture = ?
        WHERE id = ?
    """, (brand, model, size, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture, tire_id))
    conn.commit()

# Function for Import from Excel (updated for promotion_id and price_per_item)
def add_tire_import(conn, brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture): 
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO tires (brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture))
    conn.commit()
    return cursor.lastrowid

def update_tire_import(conn, tire_id, brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture): 
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE tires SET
            brand = ?,
            model = ?,
            size = ?,
            quantity = ?, 
            cost_sc = ?,
            cost_dunlop = ?,
            cost_online = ?,
            wholesale_price1 = ?,
            wholesale_price2 = ?,
            price_per_item = ?,
            promotion_id = ?,
            year_of_manufacture = ?
        WHERE id = ?
    """, (brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture, tire_id))
    conn.commit()

# Unified function to calculate prices for display based on promo type
def calculate_tire_promo_prices(price_per_item, promo_type, promo_value1, promo_value2):
    price_per_item_promo = price_per_item
    price_for_4_promo = price_per_item * 4
    promo_description_text = None

    if price_per_item is None or promo_type is None:
        return {
            'price_per_item_promo': None, 
            'price_for_4_promo': price_per_item * 4 if price_per_item is not None else None,
            'promo_description_text': None
        }

    if promo_type == 'buy_x_get_y' and promo_value1 is not None and promo_value2 is not None:
        if (promo_value1 > 0 and promo_value2 >= 0):
            if (promo_value1 + promo_value2) > 0: 
                price_per_item_promo = (price_per_item * promo_value1) / (promo_value1 + promo_value2)
                price_for_4_promo = price_per_item_promo * 4
                promo_description_text = f"ซื้อ {int(promo_value1)} แถม {int(promo_value2)} ฟรี"
            else: 
                price_per_item_promo = None
                price_for_4_promo = None
                promo_description_text = "โปรไม่ถูกต้อง (X+Y=0)"
        else: 
            price_per_item_promo = None
            price_for_4_promo = None
            promo_description_text = "โปรไม่ถูกต้อง (X,Y<=0)"
    
    elif promo_type == 'percentage_discount' and promo_value1 is not None:
        if (promo_value1 >= 0 and promo_value1 <= 100):
            price_per_item_promo = price_per_item * (1 - (promo_value1 / 100))
            price_for_4_promo = price_per_item_promo * 4
            promo_description_text = f"ลด {promo_value1}%"
        else: 
            price_per_item_promo = None
            price_for_4_promo = None
            promo_description_text = "โปรไม่ถูกต้อง (%ไม่ถูกต้อง)"
    
    elif promo_type == 'fixed_price_per_n' and promo_value1 is not None and promo_value2 is not None:
        if promo_value2 > 0:
            price_per_item_promo = promo_value1 / promo_value2
            price_for_4_promo = price_per_item_promo * 4
            promo_description_text = f"ราคา {promo_value1:.2f} บาท สำหรับ {int(promo_value2)} เส้น"
        else: 
            price_per_item_promo = None
            price_for_4_promo = None
            promo_description_text = "โปรไม่ถูกต้อง (N<=0)"
            
    if price_per_item_promo is None:
        price_per_item_promo = price_per_item
        price_for_4_promo = price_per_item * 4
        promo_description_text = None

    return {
        'price_per_item_promo': price_per_item_promo, 
        'price_for_4_promo': price_for_4_promo,
        'promo_description_text': promo_description_text
    }


def get_all_tires(conn, query=None, brand_filter='all'):
    sql_query = """
        SELECT t.*, 
               p.name AS promo_name, 
               p.type AS promo_type, 
               p.value1 AS promo_value1, 
               p.value2 AS promo_value2,
               p.is_active AS promo_is_active
        FROM tires t
        LEFT JOIN promotions p ON t.promotion_id = p.id
    """
    params = []
    conditions = []

    if query:
        search_term = f"%{query}%"
        conditions.append("(t.brand LIKE ? OR t.model LIKE ? OR t.size LIKE ?)")
        params.extend([search_term, search_term, search_term])
    
    if brand_filter != 'all':
        conditions.append("t.brand = ?")
        params.append(brand_filter)
    
    if conditions:
        sql_query += " WHERE " + " AND ".join(conditions)
    
    sql_query += " ORDER BY t.brand, t.model, t.size"
    
    cursor = conn.execute(sql_query, params)
    tires = cursor.fetchall()

    processed_tires = []
    for tire in tires:
        tire_dict = dict(tire) 
        
        # Ensure year_of_manufacture is always a string and formatted
        if 'year_of_manufacture' in tire_dict and tire_dict['year_of_manufacture'] is not None:
            if isinstance(tire_dict['year_of_manufacture'], float) and tire_dict['year_of_manufacture'].is_integer():
                tire_dict['year_of_manufacture'] = str(int(tire_dict['year_of_manufacture']))
            else:
                tire_dict['year_of_manufacture'] = str(tire_dict['year_of_manufacture'])
        else:
            tire_dict['year_of_manufacture'] = ''

        promo_calc_result = {
            'price_per_item_promo': None, 
            'price_for_4_promo': tire_dict['price_per_item'] * 4 if tire_dict['price_per_item'] is not None else None,
            'promo_description_text': None
        }

        if tire_dict['promotion_id'] is not None and tire_dict['promo_is_active'] == 1:
            promo_calc_result = calculate_tire_promo_prices(
                tire_dict['price_per_item'], 
                tire_dict['promo_type'], 
                tire_dict['promo_value1'], 
                tire_dict['promo_value2']
            )
        
        tire_dict['display_promo_price_per_item'] = promo_calc_result['price_per_item_promo']
        tire_dict['display_price_for_4'] = promo_calc_result['price_for_4_promo']
        tire_dict['display_promo_description_text'] = promo_calc_result['promo_description_text']
        
        processed_tires.append(tire_dict)
    
    return processed_tires

def update_tire_quantity(conn, tire_id, new_quantity):
    conn.execute("UPDATE tires SET quantity = ? WHERE id = ?", (new_quantity, tire_id))
    conn.commit()

def add_tire_movement(conn, tire_id, move_type, quantity_change, remaining_quantity, notes):
    timestamp = get_bkk_time().isoformat()
    conn.execute("""
        INSERT INTO tire_movements (tire_id, timestamp, type, quantity_change, remaining_quantity, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (tire_id, timestamp, move_type, quantity_change, remaining_quantity, notes))
    conn.commit()

def delete_tire(conn, tire_id):
    conn.execute("DELETE FROM tires WHERE id = ?", (tire_id,))
    conn.commit()

def get_all_tire_brands(conn):
    cursor = conn.execute("SELECT DISTINCT brand FROM tires ORDER BY brand")
    return [row['brand'] for row in cursor.fetchall()]

# --- Wheel Functions ---
def get_all_wheels(conn, query=None, brand_filter='all'):
    sql_query = "SELECT * FROM wheels"
    params = []
    conditions = []

    if query:
        search_term = f"%{query}%"
        conditions.append("(brand LIKE ? OR model LIKE ? OR pcd LIKE ? OR color LIKE ?)")
        params.extend([search_term, search_term, search_term, search_term])
    
    if brand_filter != 'all':
        conditions.append("brand = ?")
        params.append(brand_filter)
    
    if conditions:
        sql_query += " WHERE " + " AND ".join(conditions)
    
    sql_query += " ORDER BY brand, model, diameter"
    
    cursor = conn.execute(sql_query, params)
    return cursor.fetchall()

def get_wheel(conn, wheel_id):
    cursor = conn.execute("SELECT * FROM wheels WHERE id = ?", (wheel_id,))
    return cursor.fetchone()

def add_wheel(conn, brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename):
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO wheels (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename))
    conn.commit()
    return cursor.lastrowid

def update_wheel(conn, wheel_id, brand, model, diameter, pcd, width, et, color, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename):
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE wheels SET
            brand = ?,
            model = ?,
            diameter = ?,
            pcd = ?,
            width = ?,
            et = ?,
            color = ?,
            cost = ?,
            cost_online = ?,
            wholesale_price1 = ?,
            wholesale_price2 = ?,
            retail_price = ?,
            image_filename = ?
        WHERE id = ?
    """, (brand, model, diameter, pcd, width, et, color, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename, wheel_id))
    conn.commit()

def add_wheel_import(conn, brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename):
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO wheels (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename))
    conn.commit()
    return cursor.lastrowid

def update_wheel_import(conn, wheel_id, brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename):
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE wheels SET
            brand = ?,
            model = ?,
            diameter = ?,
            pcd = ?,
            width = ?,
            et = ?,
            color = ?,
            quantity = ?,
            cost = ?,
            cost_online = ?,
            wholesale_price1 = ?,
            wholesale_price2 = ?,
            retail_price = ?,
            image_filename = ?
        WHERE id = ?
    """, (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename, wheel_id))
    conn.commit()

def delete_wheel(conn, wheel_id):
    conn.execute("DELETE FROM wheels WHERE id = ?", (wheel_id,))
    conn.commit()

def get_all_wheel_brands(conn):
    cursor = conn.execute("SELECT DISTINCT brand FROM wheels ORDER BY brand")
    return [row['brand'] for row in cursor.fetchall()]

def add_wheel_fitment(conn, wheel_id, brand, model, year_start, year_end):
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO wheel_fitments (wheel_id, brand, model, year_start, year_end)
        VALUES (?, ?, ?, ?, ?)
    """, (wheel_id, brand, model, year_start, year_end))
    conn.commit()

def get_wheel_fitments(conn, wheel_id):
    cursor = conn.execute("SELECT * FROM wheel_fitments WHERE wheel_id = ? ORDER BY brand, model, year_start", (wheel_id,))
    return cursor.fetchall()

def delete_wheel_fitment(conn, fitment_id):
    conn.execute("DELETE FROM wheel_fitments WHERE id = ?", (fitment_id,))
    conn.commit()