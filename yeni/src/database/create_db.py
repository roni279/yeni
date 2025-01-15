import os
import sqlite3
from datetime import datetime

# Veritabanı yolunu belirle
db_dir = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(db_dir, 'portfoy.db')

# Eski veritabanını yedekle
if os.path.exists(db_path):
    backup_path = os.path.join(db_dir, f'portfoy_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db')
    os.rename(db_path, backup_path)
    print(f"Eski veritabanı yedeklendi: {backup_path}")

# Yeni veritabanını oluştur
conn = sqlite3.connect(db_path)

# Schema dosyasını oku ve çalıştır
with open(os.path.join(db_dir, 'schema.sql'), 'r', encoding='utf-8') as f:
    schema = f.read()
    conn.executescript(schema)

print("Veritabanı başarıyla oluşturuldu!")
conn.close() 