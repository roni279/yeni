import sqlite3
import pandas as pd
from datetime import datetime
import os

class PortfoyVeriTabani:
    def __init__(self, db_path):
        """Veritabanı bağlantısını başlat"""
        self.db_path = db_path
        
    def get_db(self):
        """Her thread için yeni bir bağlantı oluştur"""
        conn = sqlite3.connect(self.db_path)
        return conn
        
    def close_db(self, conn):
        """Bağlantıyı kapat"""
        if conn:
            conn.close()

    def schema_olustur(self):
        """Veritabanı şemasını oluştur"""
        conn = self.get_db()
        try:
            schema_dosya = os.path.join(os.path.dirname(__file__), 'schema.sql')
            with open(schema_dosya, 'r', encoding='utf-8') as f:
                conn.executescript(f.read())
            conn.commit()
            return True
        except Exception as e:
            print(f"Schema oluşturma hatası: {e}")
            return False
        finally:
            self.close_db(conn)

    def islem_ekle(self, sembol, islem_tipi, miktar, fiyat, grup_adi=None, aciklama=None):
        """Yeni işlem ekle"""
        conn = self.get_db()
        cursor = conn.cursor()
        try:
            # Önce işlemi ekle
            cursor.execute("""
                INSERT INTO islemler (sembol, islem_tipi, miktar, fiyat, aciklama)
                VALUES (?, ?, ?, ?, ?)
            """, (sembol, islem_tipi, miktar, fiyat, aciklama))
            
            # Eğer grup_adi belirtildiyse, hisseyi gruba ekle
            if grup_adi:
                self.hisse_gruba_ekle(sembol, grup_adi, cursor)
            
            conn.commit()
            return True
        except Exception as e:
            print(f"İşlem ekleme hatası: {e}")
            conn.rollback()
            return False
        finally:
            cursor.close()
            self.close_db(conn)

    def musteri_yatirim_ekle(self, musteri_id, miktar, islem_tipi='YATIRIM', aciklama=None):
        """Müşteri yatırımı ekle"""
        conn = self.get_db()
        cursor = conn.cursor()
        try:
            # İlk yatırımsa fon değerini 1.0 olarak başlat
            cursor.execute("SELECT COUNT(*) FROM fon_degerleri")
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    INSERT INTO fon_degerleri 
                    (tarih, toplam_portfoy_degeri, toplam_pay_adedi, birim_pay_degeri)
                    VALUES (CURRENT_TIMESTAMP, ?, ?, ?)
                """, (miktar if islem_tipi == 'YATIRIM' else 0, 
                    miktar if islem_tipi == 'YATIRIM' else 0, 1.0))
                birim_pay_degeri = 1.0
            else:
                # Güncel pay değerini al
                cursor.execute("""
                    SELECT birim_pay_degeri 
                    FROM fon_degerleri 
                    ORDER BY tarih DESC 
                    LIMIT 1
                """)
                birim_pay_degeri = cursor.fetchone()[0]
            
            # Pay adedini hesapla
            pay_adedi = miktar / birim_pay_degeri
            
            # Yatırımı kaydet
            cursor.execute("""
                INSERT INTO musteri_yatirimlar 
                (musteri_id, miktar, islem_tipi, birim_pay_degeri, pay_adedi, aciklama)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (musteri_id, miktar, islem_tipi, birim_pay_degeri, pay_adedi, aciklama))
            
            # Aylık yatırım hareketine ekle
            from datetime import datetime
            now = datetime.now()
            cursor.execute("""
                INSERT INTO aylik_yatirimlar 
                (yil, ay, tarih, miktar, birim_pay_degeri, pay_adedi, islem_tipi)
                VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?)
            """, (now.year, now.month, miktar, birim_pay_degeri, pay_adedi, islem_tipi))
            
            # Fon değerini güncelle
            self.fon_degerini_guncelle()
            
            # Aylık raporu güncelle
            self.aylik_rapor_guncelle(now.year, now.month)
            
            conn.commit()
            return True
            
        except Exception as e:
            print(f"Müşteri yatırım ekleme hatası: {e}")
            conn.rollback()
            return False
        finally:
            cursor.close()
            self.close_db(conn)

    def musteri_sil(self, musteri_id):
        """Müşteriyi ve ilişkili tüm yatırımlarını sil"""
        conn = self.get_db()
        cursor = conn.cursor()
        try:
            # Önce yatırımları sil
            cursor.execute("DELETE FROM musteri_yatirimlar WHERE musteri_id = ?", (musteri_id,))
            
            # Sonra müşteriyi sil
            cursor.execute("DELETE FROM musteriler WHERE id = ?", (musteri_id,))
            
            conn.commit()
            return True
        except Exception as e:
            print(f"Müşteri silme hatası: {e}")
            conn.rollback()
            return False
        finally:
            cursor.close()
            self.close_db(conn)

    def musteri_listesi(self):
        """Tüm müşterileri ve güncel durumlarını getir"""
        conn = self.get_db()
        try:
            sql = """
            WITH musteri_ozet AS (
                SELECT 
                    m.id,
                    m.ad_soyad,
                    m.telefon,
                    m.email,
                    COALESCE(SUM(CASE WHEN my.islem_tipi = 'YATIRIM' THEN my.miktar ELSE 0 END), 0) as toplam_yatirim,
                    COALESCE(SUM(CASE WHEN my.islem_tipi = 'CEKIM' THEN my.miktar ELSE 0 END), 0) as toplam_cekim,
                    COALESCE(SUM(CASE 
                        WHEN my.islem_tipi = 'YATIRIM' THEN my.pay_adedi 
                        WHEN my.islem_tipi = 'CEKIM' THEN -my.pay_adedi 
                        ELSE 0 
                    END), 0) as toplam_pay_adedi
                FROM musteriler m
                LEFT JOIN musteri_yatirimlar my ON my.musteri_id = m.id
                GROUP BY m.id, m.ad_soyad, m.telefon, m.email
            ),
            guncel_pay AS (
                SELECT birim_pay_degeri
                FROM fon_degerleri
                ORDER BY tarih DESC
                LIMIT 1
            )
            SELECT 
                mo.*,
                mo.toplam_yatirim - mo.toplam_cekim as net_yatirim,
                mo.toplam_pay_adedi * COALESCE(gp.birim_pay_degeri, 1) as guncel_deger,
                (mo.toplam_pay_adedi * COALESCE(gp.birim_pay_degeri, 1)) - (mo.toplam_yatirim - mo.toplam_cekim) as kar_zarar,
                CASE 
                    WHEN (mo.toplam_yatirim - mo.toplam_cekim) > 0 
                    THEN (((mo.toplam_pay_adedi * COALESCE(gp.birim_pay_degeri, 1)) - (mo.toplam_yatirim - mo.toplam_cekim)) * 100.0 / (mo.toplam_yatirim - mo.toplam_cekim))
                    ELSE 0 
                END as kar_zarar_yuzde
            FROM musteri_ozet mo
            CROSS JOIN guncel_pay gp
            ORDER BY mo.id DESC
            """
            return pd.read_sql_query(sql, conn)
        except Exception as e:
            print(f"Müşteri listesi hatası: {e}")
            return pd.DataFrame()
        finally:
            self.close_db(conn)

    def portfoy_raporu(self):
        """Güncel portföy durumunu getir"""
        conn = self.get_db()
        try:
            sql = """
            WITH islem_bakiye AS (
                SELECT 
                    i.sembol,
                    SUM(CASE 
                        WHEN i.islem_tipi = 'ALIM' THEN i.miktar 
                        WHEN i.islem_tipi = 'SATIM' THEN -i.miktar 
                        ELSE 0 
                    END) as adet,
                    SUM(CASE 
                        WHEN i.islem_tipi = 'ALIM' THEN i.miktar * i.fiyat 
                        WHEN i.islem_tipi = 'SATIM' THEN -i.miktar * i.fiyat 
                        ELSE 0 
                    END) as maliyet
                FROM islemler i
                GROUP BY i.sembol
                HAVING adet > 0
            ),
            hisse_bakiye AS (
                SELECT 
                    ib.sembol,
                    h.hisse_id,
                    COALESCE(pg.grup_adi, 'GENEL') as grup_adi,
                    ib.adet,
                    ib.maliyet
                FROM islem_bakiye ib
                JOIN hisseler h ON h.sembol = ib.sembol
                LEFT JOIN hisse_grup_dagilimlari hgd ON hgd.hisse_id = h.hisse_id
                LEFT JOIN portfoy_gruplari pg ON pg.grup_id = hgd.grup_id
            )
            SELECT 
                hb.sembol,
                hb.grup_adi,
                hb.adet,
                hb.maliyet,
                ROUND(hb.maliyet / hb.adet, 2) as ortalama_maliyet,
                COALESCE(
                    (SELECT fiyat 
                    FROM islemler 
                    WHERE sembol = hb.sembol 
                    ORDER BY tarih DESC 
                    LIMIT 1),
                    hb.maliyet / hb.adet
                ) as guncel_fiyat
            FROM hisse_bakiye hb
            ORDER BY hb.grup_adi, hb.sembol
            """
            
            df = pd.read_sql_query(sql, conn)
            
            if not df.empty:
                df['guncel_deger'] = df['adet'] * df['guncel_fiyat']
                df['kar_zarar'] = df['guncel_deger'] - df['maliyet']
                df['kar_zarar_yuzde'] = (df['kar_zarar'] / df['maliyet']) * 100
                
            return df
        except Exception as e:
            print(f"Portföy raporu hatası: {e}")
            return pd.DataFrame()
        finally:
            self.close_db(conn)

    def hisse_gruba_ekle(self, sembol, grup_adi, cursor=None):
        """Hisseyi gruba ekle"""
        should_close = False
        if cursor is None:
            conn = self.get_db()
            cursor = conn.cursor()
            should_close = True
        
        try:
            # Önce mevcut grup ilişkisini temizle
            cursor.execute("""
                DELETE FROM hisse_grup_dagilimlari 
                WHERE hisse_id IN (
                    SELECT hisse_id FROM hisseler WHERE sembol = ?
                )
            """, (sembol,))
            
            # Hisse ID'sini bul
            cursor.execute("SELECT hisse_id FROM hisseler WHERE sembol = ?", (sembol,))
            hisse_sonuc = cursor.fetchone()
            if not hisse_sonuc:
                return False
            
            hisse_id = hisse_sonuc[0]
            
            # Grup ID'sini bul
            cursor.execute("SELECT grup_id FROM portfoy_gruplari WHERE grup_adi = ?", (grup_adi,))
            grup_sonuc = cursor.fetchone()
            if not grup_sonuc:
                return False
            
            grup_id = grup_sonuc[0]
            
            # Yeni grup ilişkisini ekle
            cursor.execute("""
                INSERT INTO hisse_grup_dagilimlari (hisse_id, grup_id)
                VALUES (?, ?)
            """, (hisse_id, grup_id))
            
            if should_close:
                conn.commit()
            return True
        except Exception as e:
            print(f"Hisse gruba ekleme hatası: {e}")
            if should_close:
                conn.rollback()
            return False
        finally:
            if should_close:
                cursor.close()
                self.close_db(conn)

    def bist_hisseleri_ekle(self):
        """BIST'teki tüm hisseleri ekler"""
        conn = self.get_db()
        cursor = conn.cursor()
        try:
            # Önce portföy gruplarını oluştur
            for grup in ['UZUN_VADE_1', 'UZUN_VADE_2', 'TRADE']:
                cursor.execute("""
                    INSERT OR IGNORE INTO portfoy_gruplari (grup_adi)
                    VALUES (?)
                """, (grup,))

            # Tüm BIST hisselerini ekle
            hisseler = [
                ("A1CAP", "A1 Capital", "Aracı Kurum"),
                ("ACSEL", "Acıselsan Acıpayam Selüloz", "Kimya"),
                ("ADEL", "Adel Kalemcilik", "Kırtasiye"),
                ("ADESE", "Adese AVM", "Perakende"),
                ("AEFES", "Anadolu Efes", "İçecek"),
                ("AFYON", "Afyon Çimento", "Çimento"),
                ("AGESA", "Agesa Sigorta", "Sigortacılık"),
                ("AGHOL", "AG Anadolu Holding", "Holding"),
                ("AGYO", "Atakule GYO", "GYO"),
                ("AHGAZ", "Ahlatcı Doğalgaz", "Enerji"),
                ("AKBNK", "Akbank", "Bankacılık"),
                ("AKCNS", "Akçansa", "Çimento"),
                ("AKENR", "Ak Enerji", "Enerji"),
                ("AKFGY", "Akfen GYO", "GYO"),
                ("AKFYE", "Akfen Yenilenebilir Enerji", "Enerji"),
                ("AKGRT", "Aksigorta", "Sigortacılık"),
                ("AKMGY", "Akmerkez GYO", "GYO"),
                ("AKSA", "Aksa Akrilik", "Tekstil"),
                ("AKSEN", "Aksa Enerji", "Enerji"),
                ("AKSGY", "Akiş GYO", "GYO"),
                ("AKSUE", "Aksu Enerji", "Enerji"),
                ("ALARK", "Alarko Holding", "Holding"),
                ("ALBRK", "Albaraka Türk", "Bankacılık"),
                ("ALCAR", "Alarko Carrier", "Dayanıklı Tüketim"),
                ("ALCTL", "Alcatel Lucent Teletaş", "Telekomünikasyon"),
                ("ALFAS", "Alfa Solar", "Enerji"),
                ("ALGYO", "Alarko GYO", "GYO"),
                ("ALKA", "Alkim Kağıt", "Kağıt"),
                ("ALKIM", "Alkim Kimya", "Kimya"),
                ("ALMAD", "Altın Madencilik", "Madencilik"),
                ("ANELE", "Anel Elektrik", "Elektrik"),
                ("ANGEN", "Anatolia Geneworks", "Sağlık"),
                ("ANHYT", "Anadolu Hayat Emeklilik", "Sigortacılık"),
                ("ANSGR", "Anadolu Sigorta", "Sigortacılık"),
                ("ARCLK", "Arçelik", "Dayanıklı Tüketim"),
                ("ARDYZ", "ARD Bilişim", "Bilişim"),
                ("ARENA", "Arena Bilgisayar", "Bilgisayar"),
                ("ARSAN", "Arsan Tekstil", "Tekstil"),
                ("ASELS", "Aselsan", "Savunma"),
                ("ASTOR", "Astor Enerji", "Enerji"),
                ("ASUZU", "Anadolu Isuzu", "Otomotiv"),
                ("ATAGY", "Ata GYO", "GYO"),
                ("ATAKP", "Atakule GYO", "GYO"),
                ("ATLAS", "Atlas GYO", "GYO"),
                ("ATSYH", "Atlantis Yatırım", "Yatırım"),
                ("AVGYO", "Avrasya GYO", "GYO"),
                ("AVHOL", "Avrupa Holding", "Holding"),
                ("AVOD", "A.V.O.D. Gıda", "Gıda"),
                ("AVTUR", "Avrasya Petrol", "Petrol"),
                ("AYCES", "Ayces Otel", "Turizm"),
                ("AYEN", "Ayen Enerji", "Enerji"),
                ("AYES", "Ayes Çelik", "Demir-Çelik"),
                ("AYGAZ", "Aygaz", "Enerji"),
                ("AZTEK", "Aztek Teknoloji", "Teknoloji"),
                ("BAGFS", "Bagfaş", "Gübre"),
                ("BAKAB", "Bak Ambalaj", "Ambalaj"),
                ("BALAT", "Balatacilar", "Otomotiv Yan Sanayi"),
                ("BANVT", "Banvit", "Gıda"),
                ("BARMA", "Barma", "Makine"),
                ("BASCM", "Baştaş Çimento", "Çimento"),
                ("BASGZ", "Başkent Doğalgaz", "Enerji"),
                ("BAYRK", "Bayrak EBT", "Enerji"),
                ("BERA", "Bera Holding", "Holding"),
                ("BEYAZ", "Beyaz Filo", "Otomotiv"),
                ("BFREN", "Bosch Fren", "Otomotiv Yan Sanayi"),
                ("BIMAS", "BİM Mağazalar", "Perakende"),
                ("BIOEN", "Biotrend Enerji", "Enerji"),
                ("BIZIM", "Bizim Toptan", "Perakende"),
                ("BJKAS", "Beşiktaş", "Spor"),
                ("BLCYT", "Bilici Yatırım", "Yatırım"),
                ("BMSCH", "Birleşim Mühendislik", "Mühendislik"),
                ("BNTAS", "Bantaş", "Lojistik"),
                ("BOBET", "Boğaziçi Beton", "İnşaat"),
                ("BOSSA", "Bossa", "Tekstil"),
                ("BRISA", "Brisa", "Lastik"),
                ("BRKO", "Birko", "Tekstil"),
                ("BRKSN", "Berkosan", "Plastik"),
                ("BRLSM", "Birleşim Mühendislik", "Mühendislik"),
                ("BRMEN", "Birmen Enerji", "Enerji"),
                ("BRYAT", "Borusan Yatırım", "Yatırım"),
                ("BSOKE", "Batısöke Çimento", "Çimento"),
                ("BTCIM", "Batıçim", "Çimento"),
                ("BUCIM", "Bursa Çimento", "Çimento"),
                ("BURCE", "Burçelik", "Demir-Çelik"),
                ("BURVA", "Burçelik Vana", "Makine"),
                ("BVSAN", "Birikim Varlık", "Finans"),
                ("CANTE", "Çan2 Termik", "Enerji"),
                ("CASA", "Casa Emtia", "Ticaret"),
                ("CCOLA", "Coca Cola İçecek", "İçecek"),
                ("CELHA", "Çelik Halat", "Demir-Çelik"),
                ("CEMAS", "Çemaş", "Makine"),
                ("CEMTS", "Çemtaş", "Demir-Çelik"),
                ("CEOEM", "CEO Event Medya", "Medya"),
                ("CIMSA", "Çimsa", "Çimento"),
                ("CLEBI", "Çelebi Hava Servisi", "Havacılık"),
                ("CMBTN", "Çimbeton", "Çimento"),
                ("CMENT", "Çimentaş", "Çimento"),
                ("CONSE", "Consus Enerji", "Enerji"),
                ("COSMO", "Cosmos Yatırım", "Yatırım"),
                ("CRDFA", "Creditwest Faktoring", "Faktoring"),
                ("CRFSA", "CarrefourSA", "Perakende"),
                ("CUSAN", "Çuhadaroğlu Metal", "Metal"),
                ("DAGHL", "Dağ Mühendislik", "Mühendislik"),
                ("DAGI", "Dagi Giyim", "Tekstil"),
                ("DAPGM", "DAP Gayrimenkul", "GYO"),
                ("DARDL", "Dardanel", "Gıda"),
                ("DENGE", "Denge Yatırım", "Yatırım"),
                ("DERHL", "Derlüks Yatırım", "Yatırım"),
                ("DERIM", "Derim Deri", "Deri"),
                ("DESA", "Desa Deri", "Deri"),
                ("DESPC", "Despec Bilgisayar", "Bilgisayar"),
                ("DEVA", "Deva Holding", "İlaç"),
                ("DGATE", "Datagate Bilgisayar", "Bilgisayar"),
                ("DGGYO", "Doğuş GYO", "GYO"),
                ("DGNMO", "Doğanlar Mobilya", "Mobilya"),
                ("DIRIT", "Diriteks", "Tekstil"),
                ("DITAS", "Ditaş", "Otomotiv Yan Sanayi"),
                ("DJIST", "Dow Jones İstanbul", "Endeks"),
                ("DMSAS", "Demisaş Döküm", "Metal"),
                ("DNISI", "Dinamik Isı", "Makine"),
                ("DOAS", "Doğuş Otomotiv", "Otomotiv"),
                ("DOBUR", "Doğan Burda", "Medya"),
                ("DOCO", "DO & CO", "Turizm"),
                ("DOGUB", "Doğusan", "Seramik"),
                ("DOHOL", "Doğan Holding", "Holding"),
                ("DOKTA", "Döktaş", "Metal"),
                ("DURDO", "Duran Doğan", "Ambalaj"),
                ("DYOBY", "DYO Boya", "Boya"),
                ("DZGYO", "Deniz GYO", "GYO"),
                ("ECILC", "Eczacıbaşı İlaç", "İlaç"),
                ("ECZYT", "Eczacıbaşı Yatırım", "Yatırım"),
                ("EDATA", "Euro Trend", "Teknoloji"),
                ("EDIP", "Edip Gayrimenkul", "GYO"),
                ("EGEEN", "Ege Endüstri", "Otomotiv Yan Sanayi"),
                ("EGEPO", "Ege Profil", "Plastik"),
                ("EGGUB", "Ege Gübre", "Gübre"),
                ("EGPRO", "Ege Profil", "Plastik"),
                ("EGSER", "Ege Seramik", "Seramik"),
                ("EKGYO", "Emlak Konut GYO", "GYO"),
                ("EKIZ", "Ekiz Kimya", "Kimya"),
                ("EKSUN", "Eksun Gıda", "Gıda"),
                ("ELITE", "Elite Naturel", "Gıda"),
                ("EMKEL", "Emek Elektrik", "Elektrik"),
                ("EMNIS", "Eminiş Ambalaj", "Ambalaj"),
                ("ENJSA", "Enerjisa", "Enerji"),
                ("ENKAI", "Enka İnşaat", "İnşaat"),
                ("EPLAS", "Egeplast", "Plastik"),
                ("ERBOS", "Erbosan", "Metal"),
                ("EREGL", "Ereğli Demir Çelik", "Demir-Çelik"),
                ("ERSU", "Ersu Gıda", "Gıda"),
                ("ESCOM", "Escort Teknoloji", "Teknoloji"),
                ("ETILR", "Etiler Gıda", "Gıda"),
                ("ETYAT", "Euro Trend Yatırım", "Yatırım"),
                ("EUHOL", "Euro Holding", "Holding"),
                ("EUKYO", "Euro Kapital Yatırım Ortaklığı", "Yatırım"),
                ("EUYO", "Euro Yatırım Ortaklığı", "Yatırım"),
                ("FADE", "Fade Gıda", "Gıda"),
                ("FENER", "Fenerbahçe", "Spor"),
                ("FLAP", "Flap Kongre", "Turizm"),
                ("FMIZP", "Federal-Mogul İzmit", "Otomotiv Yan Sanayi"),
                ("FONET", "Fonet Bilgi Teknolojileri", "Bilişim"),
                ("FORMT", "Format Matbaacılık", "Matbaa"),
                ("FRIGO", "Frigo Pak", "Gıda"),
                ("FROTO", "Ford Otosan", "Otomotiv"),
                ("GARAN", "Garanti Bankası", "Bankacılık"),
                ("GARFA", "Garanti Faktoring", "Faktoring"),
                ("GEDIK", "Gedik Yatırım", "Yatırım"),
                ("GEDZA", "Gediz Ambalaj", "Ambalaj"),
                ("GENIL", "Gen İlaç", "İlaç"),
                ("GENTS", "Gentaş", "Orman Ürünleri"),
                ("GEREL", "Gersan Elektrik", "Elektrik"),
                ("GLBMD", "Global Yatırım", "Yatırım"),
                ("GLRYH", "Gelecek Varlık", "Finans"),
                ("GLYHO", "Global Yatırım Holding", "Holding"),
                ("GMTAS", "Gümüştaş Madencilik", "Madencilik"),
                ("GOODY", "Good-Year", "Lastik"),
                ("GOZDE", "Gözde Girişim", "Yatırım"),
                ("GRNYO", "Garanti GYO", "GYO"),
                ("GRSEL", "Gürsel Turizm", "Turizm"),
                ("GSDDE", "GSD Denizcilik", "Denizcilik"),
                ("GSDHO", "GSD Holding", "Holding"),
                ("GSRAY", "Galatasaray", "Spor"),
                ("GUBRF", "Gübre Fabrikaları", "Gübre"),
                ("GWIND", "Galata Wind Enerji", "Enerji"),
                ("GZNMI", "Gezinomi", "Turizm"),
                ("HALKB", "Halk Bankası", "Bankacılık"),
                ("HATEK", "Hateks", "Tekstil"),
                ("HDFGS", "Hedef Girişim", "Yatırım"),
                ("HEKTS", "Hektaş", "Kimya"),
                ("HLGYO", "Halk GYO", "GYO"),
                ("HUBVC", "Hub Girişim", "Yatırım"),
                ("HURGZ", "Hürriyet Gazetecilik", "Medya"),
                ("ICBCT", "ICBC Turkey Bank", "Bankacılık"),
                ("IDEAS", "İdealist Danışmanlık", "Danışmanlık"),
                ("IDGYO", "İdealist GYO", "GYO"),
                ("IEYHO", "Işıklar Enerji Yapı", "Enerji"),
                ("IHEVA", "İhlas Ev Aletleri", "Dayanıklı Tüketim"),
                ("IHGZT", "İhlas Gazetecilik", "Medya"),
                ("IHLGM", "İhlas Gayrimenkul", "GYO"),
                ("IHYAY", "İhlas Yayın Holding", "Medya"),
                ("INDES", "İndeks Bilgisayar", "Bilgisayar"),
                ("INFO", "İnfo Yatırım", "Yatırım"),
                ("INTEM", "İntema", "Yapı"),
                ("IPEKE", "İpek Enerji", "Enerji"),
                ("ISBIR", "İşbir Holding", "Holding"),
                ("ISCTR", "İş Bankası (C)", "Bankacılık"),
                ("ISDMR", "İskenderun Demir", "Demir-Çelik"),
                ("ISFIN", "İş Finansal Kiralama", "Finansal Kiralama"),
                ("ISGYO", "İş GYO", "GYO"),
                ("ISKPL", "İskur Plastik", "Plastik"),
                ("ISKUR", "İşbir Sentetik", "Tekstil"),
                ("ISMEN", "İş Yatırım", "Yatırım"),
                ("ISYAT", "İş Yatırım Ortaklığı", "Yatırım"),
                ("ITTFH", "İttifak Holding", "Holding"),
                ("IZFAS", "İzmir Fırça", "Sanayi"),
                ("IZMDC", "İzmir Demir Çelik", "Demir-Çelik"),
                ("JANTS", "Jantsa Jant", "Otomotiv Yan Sanayi"),
                ("KAPLM", "Kaplamacılar", "Metal"),
                ("KAREL", "Karel Elektronik", "Elektronik"),
                ("KARSN", "Karsan Otomotiv", "Otomotiv"),
                ("KARTN", "Kartonsan", "Kağıt"),
                ("KARYE", "Karye Mühendislik", "Mühendislik"),
                ("KATMR", "Katmerciler", "Otomotiv Yan Sanayi"),
                ("KAYSE", "Kayseri Şeker", "Gıda"),
                ("KCAER", "Kocaer Çelik", "Demir-Çelik"),
                ("KENT", "Kent Gıda", "Gıda"),
                ("KERVN", "Kervansaray Yatırım", "Turizm"),
                ("KERVT", "Kerevitaş Gıda", "Gıda"),
                ("KFEIN", "Kafein Yazılım", "Yazılım"),
                ("KGYO", "Kiler GYO", "GYO"),
                ("KIMMR", "Kimpur", "Kimya"),
                ("KLGYO", "Kiler GYO", "GYO"),
                ("KLKIM", "Kalekim", "Kimya"),
                ("KLMSN", "Klimasan Klima", "Dayanıklı Tüketim"),
                ("KLNMA", "Türkiye Kalkınma Bankası", "Bankacılık"),
                ("KMPUR", "Kimteks Poliüretan", "Kimya"),
                ("KNFRT", "Konfrut Gıda", "Gıda"),
                ("KONKA", "Konka Kağıt", "Kağıt"),
                ("KONTR", "Kontrolmatik", "Teknoloji"),
                ("KONYA", "Konya Çimento", "Çimento"),
                ("KORDS", "Kordsa Teknik", "Tekstil"),
                ("KOZAA", "Koza Anadolu Metal", "Madencilik"),
                ("KOZAL", "Koza Altın", "Madencilik"),
                ("KRDMA", "Kardemir (A)", "Demir-Çelik"),
                ("KRDMB", "Kardemir (B)", "Demir-Çelik"),
                ("KRDMD", "Kardemir (D)", "Demir-Çelik"),
                ("KRGYO", "Körfez GYO", "GYO"),
                ("KRONT", "Kron Teknoloji", "Teknoloji"),
                ("KRPLS", "Karplus Teknoloji", "Teknoloji"),
                ("KRSTL", "Kristal Kola", "İçecek"),
                ("KRTEK", "Karsu Tekstil", "Tekstil"),
                ("KRVGD", "Kervan Gıda", "Gıda"),
                ("KSTUR", "Kuştur Turizm", "Turizm"),
                ("KTLEV", "Katılım Varlık", "Finans"),
                ("KTSKR", "Kutahya Şeker", "Gıda"),
                ("KUTPO", "Kütahya Porselen", "Seramik"),
                ("KUYAS", "Kuyumcukent", "GYO"),
                ("LIDFA", "Lider Faktoring", "Faktoring"),
                ("LINK", "Link Bilgisayar", "Bilgisayar"),
                ("LKMNH", "Lokman Hekim", "Sağlık"),
                ("LOGO", "Logo Yazılım", "Yazılım"),
                ("LUKSK", "Lüks Kadife", "Tekstil"),
                ("MAALT", "Marmaris Altınyunus", "Turizm"),
                ("MACKO", "Macro", "Teknoloji"),
                ("MAGEN", "Margün Enerji", "Enerji"),
                ("MAKIM", "Makina Takım", "Makine"),
                ("MAKTK", "Makina Takım", "Makine"),
                ("MANAS", "Manas Enerji", "Enerji"),
                ("MARKA", "Marka Yatırım", "Yatırım"),
                ("MARTI", "Martı Otel", "Turizm"),
                ("MAVI", "Mavi Giyim", "Tekstil"),
                ("MEDTR", "Medical Park", "Sağlık"),
                ("MEGAP", "Mega Polietilen", "Plastik"),
                ("MEPET", "Metro Petrol", "Petrol"),
                ("MERCN", "Mercan Kimya", "Kimya"),
                ("MERIT", "Merit Turizm", "Turizm"),
                ("MERKO", "Merko Gıda", "Gıda"),
                ("METRO", "Metro Holding", "Holding"),
                ("METUR", "Metemtur Otelcilik", "Turizm"),
                ("MGROS", "Migros Ticaret", "Perakende"),
                ("MIATK", "MİA Teknoloji", "Teknoloji"),
                ("MIPAZ", "Milpa", "GYO"),
                ("MMCAS", "MMC San.", "Sanayi"),
                ("MNDRS", "Menderes Tekstil", "Tekstil"),
                ("MPARK", "MLP Sağlık", "Sağlık"),
                ("MRGYO", "Martı GYO", "GYO"),
                ("MRSHL", "Marshall", "Boya"),
                ("MSGYO", "Mistral GYO", "GYO"),
                ("MTRKS", "Matriks Bilgi", "Bilişim"),
                ("MTRYO", "Metro Yatırım", "Yatırım"),
                ("MZHLD", "Mazhar Zorlu", "Tekstil"),
                ("NATEN", "Naturel Enerji", "Enerji"),
                ("NETAS", "Netaş Telekom.", "Telekomünikasyon"),
                ("NIBAS", "Niğbaş Niğde Beton", "İnşaat"),
                ("NTGAZ", "Naturelgaz", "Enerji"),
                ("NTHOL", "Net Holding", "Holding"),
                ("NUGYO", "Nurol GYO", "GYO"),
                ("NUHCM", "Nuh Çimento", "Çimento"),
                ("OBASE", "Obase Bilgisayar", "Bilgisayar"),
                ("ODAS", "Odaş Elektrik", "Enerji"),
                ("OFSYM", "Ofis Yazılım", "Yazılım"),
                ("ONCSM", "Öncü Girişim", "Yatırım"),
                ("ORCAY", "Orçay Ortaköy Çay", "Gıda"),
                ("ORGE", "Orge Enerji", "Enerji"),
                ("ORMA", "Orma Orman", "Orman Ürünleri"),
                ("OSMEN", "Osmanlı Yatırım", "Yatırım"),
                ("OSTIM", "Ostim Endüstriyel", "Sanayi"),
                ("OTKAR", "Otokar", "Otomotiv"),
                ("OTTO", "Otto Holding", "Holding"),
                ("OYAKC", "Oyak Çimento", "Çimento"),
                ("OYAYO", "Oyak Yatırım", "Yatırım"),
                ("OYLUM", "Oylum Sınai", "Sanayi"),
                ("OYYAT", "Oyak Yatırım", "Yatırım"),
                ("OZGYO", "Özderici GYO", "GYO"),
                ("OZKGY", "Özak GYO", "GYO"),
                ("OZRDN", "Özerden Plastik", "Plastik"),
                ("PAGYO", "Panora GYO", "GYO"),
                ("PAMEL", "Pamel Yenilenebilir", "Enerji"),
                ("PAPIL", "Papilon Savunma", "Savunma"),
                ("PARSN", "Parsan", "Otomotiv Yan Sanayi"),
                ("PASEU", "Pasifik GYO", "GYO"),
                ("PCILT", "PC İletişim", "İletişim"),
                ("PEGYO", "Pera GYO", "GYO"),
                ("PEKGY", "Peker GYO", "GYO"),
                ("PENTA", "Penta Teknoloji", "Teknoloji"),
                ("PETKM", "Petkim", "Petrokimya"),
                ("PETUN", "Pınar Et ve Un", "Gıda"),
                ("PGSUS", "Pegasus", "Havayolu"),
                ("PINSU", "Pınar Su", "İçecek"),
                ("PKART", "Plastikkart", "Plastik"),
                ("PKENT", "Petrokent Turizm", "Turizm"),
                ("PNSUT", "Pınar Süt", "Gıda"),
                ("POLHO", "Polisan Holding", "Holding"),
                ("POLTK", "Politeknik Metal", "Metal"),
                ("PRDGS", "Pardus Girişim", "Yatırım"),
                ("PRKAB", "Türk Prysmian Kablo", "Kablo"),
                ("PRKME", "Park Elektrik", "Madencilik"),
                ("PRZMA", "Prizma Press", "Basım-Yayın"),
                ("PSDTC", "Pergamon Status", "Teknoloji"),
                ("QNBFB", "QNB Finansbank", "Bankacılık"),
                ("QNBFL", "QNB Finans Finansal", "Finansal Kiralama"),
                ("QUAGR", "QUA Granite", "Seramik"),
                ("RALYH", "Ralyh Menkul", "Yatırım"),
                ("RAYSG", "Ray Sigorta", "Sigortacılık"),
                ("RHEAG", "Rhea Girişim", "Yatırım"),
                ("RODRG", "Rodrigo Tekstil", "Tekstil"),
                ("ROYAL", "Royal Halı", "Tekstil"),
                ("RTALB", "RTA Laboratuvarları", "Sağlık"),
                ("RUBNS", "Rubenis Tekstil", "Tekstil"),
                ("SAFKR", "Şafak Ray", "Metal"),
                ("SAHOL", "Sabancı Holding", "Holding"),
                ("SAMAT", "Saray Matbaacılık", "Matbaa"),
                ("SANEL", "San-El Mühendislik", "Mühendislik"),
                ("SANFM", "Sanifoam Sünger", "Sanayi"),
                ("SANKO", "Sanko Pazarlama", "Ticaret"),
                ("SARKY", "Sarkuysan", "Metal"),
                ("SASA", "SASA Polyester", "Kimya"),
                ("SAYAS", "Say Reklamcılık", "Reklamcılık"),
                ("SEKFK", "Şeker Faktoring", "Faktoring"),
                ("SEKUR", "Sekuro Plastik", "Plastik"),
                ("SELEC", "Selçuk Ecza", "İlaç"),
                ("SELGD", "Selçuk Gıda", "Gıda"),
                ("SELVA", "Selva Gıda", "Gıda"),
                ("SEYKM", "Seyitler Kimya", "Kimya"),
                ("SISE", "Şişe Cam", "Cam"),
                ("SKBNK", "Şekerbank", "Bankacılık"),
                ("SKTAS", "Söktaş", "Tekstil"),
                ("SMART", "Smart Güneş", "Enerji"),
                ("SNGYO", "Sinpaş GYO", "GYO"),
                ("SNKRN", "Sankur Yatırım", "Yatırım"),
                ("SNPAM", "Sinpaş GYO", "GYO"),
                ("SODSN", "Sodaş Sodyum", "Kimya"),
                ("SOKM", "ŞOK Marketler", "Perakende"),
                ("SONME", "Sönmez Filament", "Tekstil"),
                ("SRVGY", "Servet GYO", "GYO"),
                ("SUMAS", "Sumaş", "Makine"),
                ("TACTR", "TAÇ Tarım", "Tarım"),
                ("TATGD", "Tat Gıda", "Gıda"),
                ("TAVHL", "TAV Havalimanları", "Havacılık"),
                ("TBORG", "T. Tuborg", "İçecek"),
                ("TCELL", "Turkcell", "Telekomünikasyon"),
                ("TDGYO", "Trend GYO", "GYO"),
                ("TEKTU", "Tek-Art Turizm", "Turizm"),
                ("TETMT", "Tetamat", "Gıda"),
                ("TGSAS", "TGS Dış Ticaret", "Ticaret"),
                ("THYAO", "Türk Hava Yolları", "Havayolu"),
                ("TKFEN", "Tekfen Holding", "Holding"),
                ("TKNSA", "Teknosa", "Perakende"),
                ("TLMAN", "Talya Maden", "Madencilik"),
                ("TMPOL", "Temapol Polimer", "Plastik"),
                ("TMSN", "Tümosan Motor", "Otomotiv"),
                ("TOASO", "Tofaş Oto", "Otomotiv"),
                ("TRCAS", "Turcas Petrol", "Petrol"),
                ("TRGYO", "Torunlar GYO", "GYO"),
                ("TRILC", "Trilogic Yazılım", "Yazılım"),
                ("TSGYO", "TSKB GYO", "GYO"),
                ("TSKB", "T.S.K.B.", "Bankacılık"),
                ("TSPOR", "Trabzonspor", "Spor"),
                ("TTKOM", "Türk Telekom", "Telekomünikasyon"),
                ("TTRAK", "Türk Traktör", "Otomotiv"),
                ("TUCLK", "Tuğçelik", "Metal"),
                ("TUKAS", "Tukaş", "Gıda"),
                ("TUPRS", "Tüpraş", "Petrol"),
                ("TUREX", "Tureks Turizm", "Turizm"),
                ("TURGG", "Türker Proje", "İnşaat"),
                ("TURSG", "Türkiye Sigorta", "Sigortacılık"),
                ("UFUK", "Ufuk Yatırım", "Yatırım"),
                ("ULKER", "Ülker Bisküvi", "Gıda"),
                ("ULUFA", "Ulufan Yazılım", "Yazılım"),
                ("ULUSE", "Ulusoy Elektrik", "Elektrik"),
                ("ULUUN", "Ulusoy Un", "Gıda"),
                ("UMPAS", "Umpaş Holding", "Holding"),
                ("UNLU", "Ünlü Yatırım", "Yatırım"),
                ("USAK", "Uşak Seramik", "Seramik"),
                ("UTPYA", "Utopya Turizm", "Turizm"),
                ("UZERB", "Uzertas Boya", "Boya"),
                ("VAKBN", "Vakıfbank", "Bankacılık"),
                ("VAKFN", "Vakıf Fin. Kir.", "Finansal Kiralama"),
                ("VAKKO", "Vakko Tekstil", "Tekstil"),
                ("VANGD", "Van Et", "Gıda"),
                ("VERTU", "Verusaturk", "Yatırım"),
                ("VESBE", "Vestel Beyaz Eşya", "Dayanıklı Tüketim"),
                ("VESTL", "Vestel", "Elektronik"),
                ("VKFYO", "Vakıf Yatırım Ortaklığı", "Yatırım"),
                ("VKGYO", "Vakıf GYO", "GYO"),
                ("VKING", "Viking Kağıt", "Kağıt"),
                ("YAPRK", "Yaprak Süt", "Gıda"),
                ("YATAS", "Yataş", "Mobilya"),
                ("YAYLA", "Yayla Enerji", "Enerji"),
                ("YBTAS", "YB Tasarruf", "Finans"),
                ("YESIL", "Yeşil Yatırım", "Yatırım"),
                ("YGGYO", "Yeni Gimat GYO", "GYO"),
                ("YGYO", "Yeşil GYO", "GYO"),
                ("YKBNK", "Yapı Kredi", "Bankacılık"),
                ("YKSLN", "Yükselen Çelik", "Demir-Çelik"),
                ("YONGA", "Yonga Mobilya", "Mobilya"),
                ("YUNSA", "Yünsa", "Tekstil"),
                ("YYAPI", "Yesil Yapı", "İnşaat"),
                ("ZEDUR", "Zedur Enerji", "Enerji"),
                ("ZOREN", "Zorlu Enerji", "Enerji"),
                ("ZRGYO", "Ziraat GYO", "GYO")
            ]
            
            print(f"Toplam {len(hisseler)} hisse eklenecek...")
            eklenen_hisseler = []
            
            for i, (sembol, sirket_adi, sektor) in enumerate(hisseler, 1):
                try:
                    print(f"\r{i}/{len(hisseler)} - {sembol} ekleniyor...", end="", flush=True)
                    # Önce sektörü bul veya ekle
                    cursor.execute("""
                        INSERT OR IGNORE INTO sektorler (sektor_adi)
                        VALUES (?)
                    """, (sektor,))
                    
                    cursor.execute("""
                        SELECT sektor_id FROM sektorler WHERE sektor_adi = ?
                    """, (sektor,))
                    sektor_id = cursor.fetchone()[0]
                    
                    # Hisseyi ekle
                    cursor.execute("""
                        INSERT OR IGNORE INTO hisseler (sembol, sirket_adi, sektor_id)
                        VALUES (?, ?, ?)
                    """, (sembol, sirket_adi, sektor_id))
                    
                    eklenen_hisseler.append(sembol)
                except Exception as e:
                    print(f"\nHata ({sembol}): {e}")
                    continue
            
            conn.commit()
            print(f"\n\nToplam {len(eklenen_hisseler)} hisse başarıyla eklendi:")
            print(", ".join(eklenen_hisseler))
            return eklenen_hisseler
            
        except Exception as e:
            print(f"BIST hisseleri ekleme hatası: {e}")
            conn.rollback()
            return []
        finally:
            cursor.close()
            self.close_db(conn)

    def fon_degerini_guncelle(self):
        """Fonun güncel değerini hesapla ve kaydet"""
        conn = self.get_db()
        cursor = conn.cursor()
        try:
            # 1. Tüm portföyün güncel değerini hesapla
            cursor.execute("""
                SELECT COALESCE(SUM(i.miktar * 
                    (SELECT fiyat FROM islemler 
                    WHERE sembol = i.sembol 
                    ORDER BY tarih DESC LIMIT 1)
                ), 0) as toplam_deger
                FROM (
                    SELECT sembol, SUM(CASE 
                        WHEN islem_tipi = 'ALIM' THEN miktar
                        WHEN islem_tipi = 'SATIM' THEN -miktar
                        ELSE 0 
                    END) as miktar
                    FROM islemler
                    GROUP BY sembol
                    HAVING miktar > 0
                ) i
            """)
            toplam_portfoy_degeri = cursor.fetchone()[0]
            
            # 2. Toplam pay adedini al
            cursor.execute("""
                SELECT COALESCE(SUM(CASE 
                    WHEN islem_tipi = 'YATIRIM' THEN pay_adedi 
                    WHEN islem_tipi = 'CEKIM' THEN -pay_adedi 
                    ELSE 0 
                END), 0)
                FROM musteri_yatirimlar
            """)
            toplam_pay_adedi = cursor.fetchone()[0] or 1  # Pay adedi 0 olmasın
            
            # 3. Birim pay değerini hesapla
            birim_pay_degeri = toplam_portfoy_degeri / toplam_pay_adedi
            
            # 4. Yeni fon değerini kaydet
            cursor.execute("""
                INSERT INTO fon_degerleri 
                (tarih, toplam_portfoy_degeri, toplam_pay_adedi, birim_pay_degeri)
                VALUES (CURRENT_TIMESTAMP, ?, ?, ?)
            """, (toplam_portfoy_degeri, toplam_pay_adedi, birim_pay_degeri))
            
            conn.commit()
            return birim_pay_degeri
            
        except Exception as e:
            print(f"Fon değeri güncelleme hatası: {e}")
            conn.rollback()
            return None
        finally:
            cursor.close()
            self.close_db(conn)

    def aylik_rapor_guncelle(self, yil, ay):
        """Aylık raporu güncelle"""
        conn = self.get_db()
        cursor = conn.cursor()
        try:
            # 1. Ay başı ve ay sonu tarihlerini belirle
            ay_basi = f"{yil}-{ay:02d}-01"
            ay_sonu = f"{yil}-{ay:02d}-31" if ay != 12 else f"{yil}-12-31"
            
            # 2. Önceki aydan devreden değerleri al
            cursor.execute("""
                SELECT bitis_deger, toplam_pay_adedi, bitis_pay_degeri
                FROM aylik_islemler
                WHERE (yil < ? OR (yil = ? AND ay < ?))
                ORDER BY yil DESC, ay DESC
                LIMIT 1
            """, (yil, yil, ay))
            row = cursor.fetchone()
            
            if row:
                baslangic_deger = row[0]
                baslangic_pay_adedi = row[1]
                baslangic_pay_degeri = row[2]
            else:
                baslangic_deger = 0
                baslangic_pay_adedi = 0
                baslangic_pay_degeri = 1.0
            
            # 3. Bu aydaki yatırım hareketlerini topla
            cursor.execute("""
                SELECT 
                    COALESCE(SUM(CASE WHEN islem_tipi = 'YATIRIM' THEN miktar ELSE -miktar END), 0) as net_yatirim,
                    COALESCE(SUM(CASE WHEN islem_tipi = 'YATIRIM' THEN pay_adedi ELSE -pay_adedi END), 0) as net_pay_adedi
                FROM aylik_yatirimlar
                WHERE yil = ? AND ay = ?
            """, (yil, ay))
            net_yatirim, net_pay_adedi = cursor.fetchone()
            
            # 4. Ay sonu değerleri hesapla
            toplam_pay_adedi = baslangic_pay_adedi + net_pay_adedi
            
            # Güncel fon değerini al
            cursor.execute("""
                SELECT birim_pay_degeri
                FROM fon_degerleri
                WHERE tarih <= ?
                ORDER BY tarih DESC
                LIMIT 1
            """, (ay_sonu,))
            bitis_pay_degeri = cursor.fetchone()[0]
            
            # Ay sonu toplam değer
            bitis_deger = toplam_pay_adedi * bitis_pay_degeri
            
            # Toplam maliyet (önceki ay + bu ayki net yatırım)
            toplam_maliyet = baslangic_deger + net_yatirim
            
            # Kar/zarar hesapla
            kar_zarar = bitis_deger - toplam_maliyet
            kar_zarar_yuzde = (kar_zarar / toplam_maliyet * 100) if toplam_maliyet > 0 else 0
            
            # 5. Raporu güncelle/ekle
            cursor.execute("""
                INSERT OR REPLACE INTO aylik_islemler 
                (yil, ay, toplam_maliyet, baslangic_deger, bitis_deger,
                toplam_pay_adedi, baslangic_pay_degeri, bitis_pay_degeri,
                kar_zarar, kar_zarar_yuzde)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (yil, ay, toplam_maliyet, baslangic_deger, bitis_deger,
                toplam_pay_adedi, baslangic_pay_degeri, bitis_pay_degeri,
                kar_zarar, kar_zarar_yuzde))  # 10 parametre
            
            conn.commit()
            return True
            
        except Exception as e:
            print(f"Aylık rapor güncelleme hatası: {e}")
            conn.rollback()
            return False
        finally:
            cursor.close()
            self.close_db(conn)

    def aylik_islem_raporu(self, yil, ay):
        """Aylık hisse işlem raporunu getir"""
        conn = self.get_db()
        try:
            sql = """
            WITH aylik_islemler AS (
                SELECT 
                    i.sembol,
                    SUM(CASE WHEN i.islem_tipi = 'ALIM' THEN i.miktar ELSE 0 END) as toplam_alim_lot,
                    SUM(CASE WHEN i.islem_tipi = 'ALIM' THEN i.miktar * i.fiyat ELSE 0 END) as toplam_alim_tutar,
                    SUM(CASE WHEN i.islem_tipi = 'SATIM' THEN i.miktar ELSE 0 END) as toplam_satim_lot,
                    SUM(CASE WHEN i.islem_tipi = 'SATIM' THEN i.miktar * i.fiyat ELSE 0 END) as toplam_satim_tutar
                FROM islemler i
                WHERE strftime('%Y', i.tarih) = ? 
                AND strftime('%m', i.tarih) = ?
                AND i.islem_tipi IN ('ALIM', 'SATIM')
                GROUP BY i.sembol
                HAVING toplam_alim_lot > 0 OR toplam_satim_lot > 0
            )
            SELECT 
                sembol,
                toplam_alim_lot,
                toplam_alim_tutar,
                CASE 
                    WHEN toplam_alim_lot > 0 
                    THEN ROUND(toplam_alim_tutar / toplam_alim_lot, 2)
                    ELSE 0 
                END as ortalama_alim_fiyat,
                toplam_satim_lot,
                toplam_satim_tutar,
                CASE 
                    WHEN toplam_satim_lot > 0 
                    THEN ROUND(toplam_satim_tutar / toplam_satim_lot, 2)
                    ELSE 0 
                END as ortalama_satim_fiyat,
                CASE 
                    WHEN toplam_satim_lot > 0 
                    THEN toplam_satim_tutar - (toplam_satim_lot * (
                        CASE 
                            WHEN toplam_alim_lot > 0 
                            THEN ROUND(toplam_alim_tutar / toplam_alim_lot, 2)
                            ELSE 0 
                        END
                    ))
                    ELSE 0 
                END as net_kar_zarar
            FROM aylik_islemler
            ORDER BY net_kar_zarar DESC
            """
            return pd.read_sql_query(sql, conn, params=(str(yil), str(ay).zfill(2)))
        except Exception as e:
            print(f"Aylık işlem raporu hatası: {e}")
            return pd.DataFrame()
        finally:
            self.close_db(conn)

    def grup_raporu(self):
        """Grup bazında portföy dağılımını getir"""
        conn = self.get_db()
        try:
            sql = """
            WITH portfoy AS (
                SELECT 
                    i.sembol,
                    SUM(CASE 
                        WHEN i.islem_tipi = 'ALIM' THEN i.miktar 
                        WHEN i.islem_tipi = 'SATIM' THEN -i.miktar 
                        ELSE 0 
                    END) as adet,
                    SUM(CASE 
                        WHEN i.islem_tipi = 'ALIM' THEN i.miktar * i.fiyat 
                        WHEN i.islem_tipi = 'SATIM' THEN -i.miktar * i.fiyat 
                        ELSE 0 
                    END) as maliyet
                FROM islemler i
                GROUP BY i.sembol
                HAVING adet > 0
            )
            SELECT 
                h.sembol,
                COALESCE(pg.grup_adi, 'GENEL') as grup_adi,
                p.adet,
                p.maliyet as grup_maliyet,
                COALESCE(
                    (SELECT fiyat 
                    FROM islemler 
                    WHERE sembol = h.sembol 
                    ORDER BY tarih DESC 
                    LIMIT 1),
                    p.maliyet / p.adet
                ) as guncel_fiyat
            FROM portfoy p
            JOIN hisseler h ON h.sembol = p.sembol
            LEFT JOIN hisse_grup_dagilimlari hgd ON hgd.hisse_id = h.hisse_id
            LEFT JOIN portfoy_gruplari pg ON pg.grup_id = hgd.grup_id
            ORDER BY grup_adi, h.sembol
            """
            return pd.read_sql_query(sql, conn)
        except Exception as e:
            print(f"Grup raporu hatası: {e}")
            return pd.DataFrame()
        finally:
            self.close_db(conn)

    def bakiye_raporu(self):
        """Toplam para ve yatırım durumunu getir"""
        conn = self.get_db()
        cursor = conn.cursor()
        try:
            # Toplam ana parayı hesapla
            cursor.execute("""
                SELECT COALESCE(SUM(CASE 
                    WHEN islem_tipi = 'YATIRIM' THEN miktar 
                    WHEN islem_tipi = 'CEKIM' THEN -miktar 
                    ELSE 0 
                END), 0) as toplam_ana_para
                FROM musteri_yatirimlar
            """)
            toplam_ana_para = cursor.fetchone()[0]
            
            # Hisselere yatırılan toplam parayı hesapla
            cursor.execute("""
                SELECT COALESCE(SUM(CASE 
                    WHEN islem_tipi = 'ALIM' THEN miktar * fiyat
                    WHEN islem_tipi = 'SATIM' THEN -(miktar * fiyat)
                    ELSE 0 
                END), 0) as yatirima_giden
                FROM islemler
                WHERE islem_tipi IN ('ALIM', 'SATIM')
            """)
            yatirima_giden = cursor.fetchone()[0]
            
            # Güncel bakiyeyi hesapla
            guncel_bakiye = toplam_ana_para - yatirima_giden
            
            return {
                'toplam_ana_para': toplam_ana_para,
                'yatirima_giden': yatirima_giden,
                'guncel_bakiye': guncel_bakiye
            }
            
        except Exception as e:
            print(f"Bakiye raporu hatası: {e}")
            return None
        finally:
            cursor.close()
            self.close_db(conn)

    def hisse_listele(self):
        """Tüm hisseleri listele"""
        conn = self.get_db()
        try:
            sql = """
            SELECT 
                h.sembol,
                h.sirket_adi,
                s.sektor_adi
            FROM hisseler h
            LEFT JOIN sektorler s ON s.sektor_id = h.sektor_id
            ORDER BY h.sembol
            """
            return pd.read_sql_query(sql, conn)
        except Exception as e:
            print(f"Hisse listeleme hatası: {e}")
            return pd.DataFrame()
        finally:
            self.close_db(conn)

    def islem_listele(self):
        """Tüm işlemleri listele"""
        conn = self.get_db()
        try:
            sql = """
            SELECT 
                datetime(i.tarih) as tarih,
                i.sembol,
                i.islem_tipi,
                i.miktar,
                i.fiyat,
                i.miktar * i.fiyat as toplam_tutar,
                i.aciklama,
                pg.grup_adi
            FROM islemler i
            LEFT JOIN hisseler h ON h.sembol = i.sembol
            LEFT JOIN hisse_grup_dagilimlari hgd ON hgd.hisse_id = h.hisse_id
            LEFT JOIN portfoy_gruplari pg ON pg.grup_id = hgd.grup_id
            ORDER BY i.tarih DESC
            """
            df = pd.read_sql_query(sql, conn, parse_dates=['tarih'])
            return df
        except Exception as e:
            print(f"İşlem listeleme hatası: {e}")
            return pd.DataFrame()
        finally:
            self.close_db(conn)

    def musteri_ekle(self, ad_soyad, telefon=None, email=None):
        """Yeni müşteri ekle"""
        conn = self.get_db()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO musteriler (ad_soyad, telefon, email)
                VALUES (?, ?, ?)
            """, (ad_soyad, telefon, email))
            musteri_id = cursor.lastrowid
            conn.commit()
            return musteri_id
        except Exception as e:
            print(f"Müşteri ekleme hatası: {e}")
            conn.rollback()
            return None
        finally:
            cursor.close()
            self.close_db(conn)

    def grup_ekle(self, grup_adi, hedef_oran, aciklama=None):
        """Yeni portföy grubu ekle"""
        conn = self.get_db()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO portfoy_gruplari (grup_adi, hedef_oran, aciklama)
                VALUES (?, ?, ?)
            """, (grup_adi, hedef_oran, aciklama))
            conn.commit()
            return True
        except Exception as e:
            print(f"Grup ekleme hatası: {e}")
            conn.rollback()
            return False
        finally:
            cursor.close()
            self.close_db(conn)

    def islem_gecmisi_temizle(self):
        """Tüm işlem geçmişini temizle"""
        conn = self.get_db()
        cursor = conn.cursor()
        try:
            # İşlemleri temizle
            cursor.execute("DELETE FROM islemler")
            # Aylık işlem özetlerini temizle
            cursor.execute("DELETE FROM aylik_islemler")
            conn.commit()
            return True
        except Exception as e:
            print(f"İşlem geçmişi temizleme hatası: {e}")
            conn.rollback()
            return False
        finally:
            cursor.close()
            self.close_db(conn)

    def hisse_fiyat_guncelle(self, sembol, guncel_fiyat):
        """Hisse senedinin güncel fiyatını güncelle"""
        conn = self.get_db()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO islemler (sembol, islem_tipi, miktar, fiyat, aciklama)
                VALUES (?, 'GUNCELLEME', 0, ?, 'Otomatik fiyat güncellemesi')
            """, (sembol, guncel_fiyat))
            
            conn.commit()
            
            # Fon değerini güncelle
            self.fon_degerini_guncelle()
            
            return True
        except Exception as e:
            print(f"Fiyat güncelleme hatası: {e}")
            conn.rollback()
            return False
        finally:
            cursor.close()
            self.close_db(conn)

    def close(self):
        """Veritabanı bağlantısını kapat - Flask uyumluluğu için"""
        conn = getattr(self, '_connection', None)
        if conn:
            self.close_db(conn)

    def musteri_islem_gecmisi(self, musteri_id):
        """Müşterinin işlem geçmişini getir"""
        conn = self.get_db()
        try:
            sql = """
            SELECT 
                datetime(tarih) as tarih,
                islem_tipi,
                miktar,
                birim_pay_degeri,
                pay_adedi,
                aciklama
            FROM musteri_yatirimlar
            WHERE musteri_id = ?
            ORDER BY tarih DESC
            """
            return pd.read_sql_query(sql, conn, params=(musteri_id,), parse_dates=['tarih'])
        except Exception as e:
            print(f"Müşteri işlem geçmişi hatası: {e}")
            return pd.DataFrame()
        finally:
            self.close_db(conn)

    def aylik_rapor(self, yil, ay):
        """Aylık işlem raporunu getir"""
        conn = self.get_db()
        try:
            sql = """
            WITH aylik_islemler AS (
                SELECT 
                    i.sembol,
                    h.sirket_adi,
                    s.sektor_adi,
                    SUM(CASE WHEN i.islem_tipi = 'ALIM' THEN i.miktar ELSE 0 END) as alim_lot,
                    SUM(CASE WHEN i.islem_tipi = 'ALIM' THEN i.miktar * i.fiyat ELSE 0 END) as alim_tutar,
                    SUM(CASE WHEN i.islem_tipi = 'SATIM' THEN i.miktar ELSE 0 END) as satim_lot,
                    SUM(CASE WHEN i.islem_tipi = 'SATIM' THEN i.miktar * i.fiyat ELSE 0 END) as satim_tutar,
                    MAX(CASE WHEN i.islem_tipi = 'GUNCELLEME' THEN i.fiyat ELSE NULL END) as guncel_fiyat,
                    MIN(CASE WHEN i.islem_tipi IN ('ALIM', 'SATIM') THEN i.fiyat ELSE NULL END) as baslangic_deger,
                    MAX(CASE WHEN i.islem_tipi IN ('ALIM', 'SATIM') THEN i.fiyat ELSE NULL END) as bitis_deger
                FROM islemler i
                JOIN hisseler h ON h.sembol = i.sembol
                LEFT JOIN sektorler s ON s.sektor_id = h.sektor_id
                WHERE strftime('%Y', i.tarih) = ?
                AND strftime('%m', i.tarih) = ?
                GROUP BY i.sembol, h.sirket_adi, s.sektor_adi
            )
            SELECT 
                sembol,
                sirket_adi,
                sektor_adi,
                alim_lot,
                alim_tutar as toplam_maliyet,
                baslangic_deger,
                bitis_deger,
                CASE WHEN alim_lot > 0 THEN alim_tutar / alim_lot ELSE 0 END as ortalama_alim,
                satim_lot,
                satim_tutar,
                CASE WHEN satim_lot > 0 THEN satim_tutar / satim_lot ELSE 0 END as ortalama_satim,
                guncel_fiyat,
                (alim_lot - satim_lot) as kalan_lot,
                CASE 
                    WHEN satim_lot > 0 
                    THEN satim_tutar - (satim_lot * (CASE WHEN alim_lot > 0 THEN alim_tutar / alim_lot ELSE 0 END))
                    ELSE (alim_lot - satim_lot) * guncel_fiyat - alim_tutar
                END as kar_zarar,
                CASE 
                    WHEN satim_lot > 0 AND alim_tutar > 0
                    THEN ((satim_tutar - (satim_lot * (alim_tutar / alim_lot))) / (satim_lot * (alim_tutar / alim_lot))) * 100
                    WHEN alim_tutar > 0
                    THEN (((alim_lot - satim_lot) * guncel_fiyat - alim_tutar) / alim_tutar) * 100
                    ELSE 0 
                END as kar_zarar_yuzde
            FROM aylik_islemler
            WHERE alim_lot > 0 OR satim_lot > 0
            ORDER BY kar_zarar DESC
            """
            
            df = pd.read_sql_query(sql, conn, params=(str(yil), str(ay).zfill(2)))
            return df
            
        except Exception as e:
            print(f"Aylık rapor hatası: {e}")
            return pd.DataFrame()
        finally:
            self.close_db(conn)

    def guncel_pay_degeri(self):
        """Güncel pay değerini getir"""
        conn = self.get_db()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT 
                    birim_pay_degeri,
                    toplam_portfoy_degeri,
                    toplam_pay_adedi,
                    datetime(tarih) as tarih
                FROM fon_degerleri 
                ORDER BY tarih DESC 
                LIMIT 1
            """)
            sonuc = cursor.fetchone()
            if sonuc:
                return {
                    'birim_pay_degeri': sonuc[0],
                    'toplam_portfoy_degeri': sonuc[1],
                    'toplam_pay_adedi': sonuc[2],
                    'tarih': sonuc[3]
                }
            return None
        except Exception as e:
            print(f"Pay değeri getirme hatası: {e}")
            return None
        finally:
            cursor.close()
            self.close_db(conn)