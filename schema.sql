DROP TABLE IF EXISTS tires;
DROP TABLE IF EXISTS wheels;
DROP TABLE IF EXISTS tire_movements;
DROP TABLE IF EXISTS wheel_movements;
DROP TABLE IF EXISTS wheel_fitments;

CREATE TABLE tires (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand TEXT NOT NULL,
    model TEXT NOT NULL,
    size TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    cost_sc REAL NOT NULL,
    cost_dunlop REAL,
    cost_online REAL, -- เพิ่มคอลัมน์นี้
    wholesale_price1 REAL, -- เพิ่มคอลัมน์นี้
    wholesale_price2 REAL, -- เพิ่มคอลัมน์นี้
    retail_price REAL NOT NULL, -- เพิ่มคอลัมน์นี้
    year_of_manufacture INTEGER,
    UNIQUE (brand, model, size) ON CONFLICT REPLACE
);

CREATE TABLE wheels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand TEXT NOT NULL,
    model TEXT NOT NULL,
    diameter REAL NOT NULL, -- เปลี่ยนเป็น REAL เพื่อรองรับค่าทศนิยมเช่น 17.5
    pcd TEXT NOT NULL,
    width REAL NOT NULL, -- เปลี่ยนเป็น REAL
    et INTEGER,
    color TEXT,
    quantity INTEGER NOT NULL DEFAULT 0,
    cost REAL NOT NULL,
    cost_online REAL, -- เพิ่มคอลัมน์นี้
    wholesale_price1 REAL, -- เพิ่มคอลัมน์นี้
    wholesale_price2 REAL, -- เพิ่มคอลัมน์นี้
    retail_price REAL NOT NULL, -- เพิ่มคอลัมน์นี้
    image_filename TEXT,
    UNIQUE (brand, model, diameter, pcd, width, et, color) ON CONFLICT REPLACE
);

CREATE TABLE tire_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tire_id INTEGER NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    type TEXT NOT NULL, -- 'IN' or 'OUT'
    quantity_change INTEGER NOT NULL,
    remaining_quantity INTEGER NOT NULL,
    notes TEXT,
    FOREIGN KEY (tire_id) REFERENCES tires (id)
);

CREATE TABLE wheel_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wheel_id INTEGER NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    type TEXT NOT NULL, -- 'IN' or 'OUT'
    quantity_change INTEGER NOT NULL,
    remaining_quantity INTEGER NOT NULL,
    notes TEXT,
    FOREIGN KEY (wheel_id) REFERENCES wheels (id)
);

CREATE TABLE wheel_fitments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wheel_id INTEGER NOT NULL,
    brand TEXT NOT NULL,
    model TEXT NOT NULL,
    year_start INTEGER NOT NULL,
    year_end INTEGER,
    UNIQUE (wheel_id, brand, model, year_start, year_end) ON CONFLICT REPLACE,
    FOREIGN KEY (wheel_id) REFERENCES wheels (id)
);