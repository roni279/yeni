-- Sektör tablosu
CREATE TABLE IF NOT EXISTS sektorler (
    sektor_id INTEGER PRIMARY KEY,
    sektor_adi VARCHAR(50) UNIQUE
);

-- Hisseler ana tablosu
CREATE TABLE IF NOT EXISTS hisseler (
    hisse_id INTEGER PRIMARY KEY,
    sembol VARCHAR(10) UNIQUE,
    sirket_adi VARCHAR(100),
    sektor_id INTEGER,
    FOREIGN KEY (sektor_id) REFERENCES sektorler(sektor_id)
);

-- İşlemler tablosu
CREATE TABLE IF NOT EXISTS islemler (
    islem_id INTEGER PRIMARY KEY,
    sembol TEXT NOT NULL,
    islem_tipi TEXT NOT NULL,  -- ALIM/SATIM
    miktar INTEGER NOT NULL,
    fiyat DECIMAL(10,2) NOT NULL,
    tarih DATETIME DEFAULT CURRENT_TIMESTAMP,
    aciklama TEXT
);

-- Aylık işlem özeti tablosu (GÜNCELLENDİ)
CREATE TABLE IF NOT EXISTS aylik_islemler (
    ozet_id INTEGER PRIMARY KEY,
    yil INTEGER NOT NULL,
    ay INTEGER NOT NULL,
    toplam_maliyet DECIMAL(20,2) DEFAULT 0,  -- Toplam yatırılan para
    baslangic_deger DECIMAL(20,2) DEFAULT 0, -- Ay başı değer
    bitis_deger DECIMAL(20,2) DEFAULT 0,     -- Ay sonu değer
    toplam_pay_adedi REAL DEFAULT 0,         -- Toplam pay adedi
    baslangic_pay_degeri REAL DEFAULT 0,     -- Ay başı pay değeri
    bitis_pay_degeri REAL DEFAULT 0,         -- Ay sonu pay değeri
    kar_zarar DECIMAL(20,2) DEFAULT 0,       -- Ay sonu kar/zarar
    kar_zarar_yuzde DECIMAL(10,2) DEFAULT 0, -- Yüzdesel kar/zarar
    UNIQUE(yil, ay)
);

-- Portföy grupları tablosu
CREATE TABLE IF NOT EXISTS portfoy_gruplari (
    grup_id INTEGER PRIMARY KEY,
    grup_adi VARCHAR(50),  -- 'UZUN_VADE_1', 'UZUN_VADE_2', 'TRADE'
    hedef_oran DECIMAL(5,2),  -- 35.00, 35.00, 30.00
    aciklama TEXT
);

-- Hisse-Grup ilişki tablosu
CREATE TABLE IF NOT EXISTS hisse_grup_dagilimlari (
    dagitim_id INTEGER PRIMARY KEY,
    hisse_id INTEGER,
    grup_id INTEGER,
    hedef_oran DECIMAL(5,2),  -- Grup içindeki hedef oranı
    FOREIGN KEY (hisse_id) REFERENCES hisseler(hisse_id),
    FOREIGN KEY (grup_id) REFERENCES portfoy_gruplari(grup_id)
);

-- Kullanıcılar tablosu
CREATE TABLE IF NOT EXISTS kullanicilar (
    kullanici_id INTEGER PRIMARY KEY AUTOINCREMENT,
    kullanici_adi TEXT UNIQUE NOT NULL,
    sifre_hash TEXT NOT NULL,
    son_giris DATETIME
);

-- Portföy özet tablosu (pay değeri takibi için)
CREATE TABLE IF NOT EXISTS portfoy_ozet (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tarih DATETIME DEFAULT CURRENT_TIMESTAMP,
    guncel_pay_degeri REAL NOT NULL DEFAULT 1.0,
    toplam_pay_adedi REAL NOT NULL DEFAULT 0
);

-- Müşteri tabloları
CREATE TABLE IF NOT EXISTS musteriler (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ad_soyad TEXT NOT NULL,
    telefon TEXT,
    email TEXT,
    kayit_tarihi DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Fon değerleri tablosu (YENİ)
CREATE TABLE IF NOT EXISTS fon_degerleri (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tarih DATETIME DEFAULT CURRENT_TIMESTAMP,
    toplam_portfoy_degeri REAL NOT NULL,
    toplam_pay_adedi REAL NOT NULL,
    birim_pay_degeri REAL NOT NULL
);

-- Müşteri yatırımlar tablosunu güncelle
CREATE TABLE IF NOT EXISTS musteri_yatirimlar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    musteri_id INTEGER NOT NULL,
    tarih DATETIME DEFAULT CURRENT_TIMESTAMP,
    miktar REAL NOT NULL,
    islem_tipi TEXT NOT NULL,  -- YATIRIM veya CEKIM
    birim_pay_degeri REAL NOT NULL,
    pay_adedi REAL NOT NULL,
    aciklama TEXT,
    FOREIGN KEY (musteri_id) REFERENCES musteriler(id)
);

-- Müşteri portföy tablosu
CREATE TABLE IF NOT EXISTS musteri_portfoy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    musteri_id INTEGER NOT NULL,
    sembol TEXT NOT NULL,
    adet INTEGER NOT NULL,
    maliyet REAL NOT NULL,
    tarih DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (musteri_id) REFERENCES musteriler(id)
);

-- Aylık yatırım hareketleri tablosu (YENİ)
CREATE TABLE IF NOT EXISTS aylik_yatirimlar (
    id INTEGER PRIMARY KEY,
    yil INTEGER NOT NULL,
    ay INTEGER NOT NULL,
    tarih DATETIME NOT NULL,
    miktar DECIMAL(20,2) NOT NULL,
    birim_pay_degeri REAL NOT NULL,
    pay_adedi REAL NOT NULL,
    islem_tipi TEXT NOT NULL  -- YATIRIM veya CEKIM
); 