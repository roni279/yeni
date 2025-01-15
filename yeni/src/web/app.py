from flask import Flask, render_template, request, jsonify, g
import pandas as pd
import json
import sys
import os
from datetime import datetime
import requests
import time

# Ana dizini (src) Python path'ine ekle
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(src_dir)

from database.portfoy_db import PortfoyVeriTabani

app = Flask(__name__)

# Veritabanı yolunu PythonAnywhere için güncelle
db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'database', 'portfoy.db')
db = PortfoyVeriTabani(db_path)

@app.route('/')
def index():
    portfoy_df = db.portfoy_raporu()
    
    # Güncel pay değerini al
    guncel_pay_degeri = db.guncel_pay_degeri()
    
    # Bakiye bilgisini al
    bakiye = db.bakiye_raporu()
    
    # Tekrarlanan kayıtları grupla
    if not portfoy_df.empty:
        portfoy_df = portfoy_df.groupby(['sembol', 'grup_adi']).agg({
            'adet': 'sum',
            'maliyet': 'sum',
            'guncel_fiyat': 'first'
        }).reset_index()
        
        # Hesaplamaları yap
        portfoy_df['guncel_deger'] = portfoy_df['adet'] * portfoy_df['guncel_fiyat']
        portfoy_df['kar_zarar'] = portfoy_df['guncel_deger'] - portfoy_df['maliyet']
        portfoy_df['kar_zarar_yuzde'] = (portfoy_df['kar_zarar'] / portfoy_df['maliyet']) * 100
        
        portfoy_list = portfoy_df.to_dict('records')
    else:
        portfoy_list = []
    
    # Grup bazında portföy verilerini hazırla
    gruplar = {}
    for grup in ['UZUN_VADE_1', 'UZUN_VADE_2', 'TRADE']:
        grup_df = portfoy_df[portfoy_df['grup_adi'] == grup] if not portfoy_df.empty else pd.DataFrame()
        if not grup_df.empty:
            gruplar[grup] = grup_df.to_dict('records')
    
    return render_template('index.html', 
                         portfoy=portfoy_list,
                         gruplar=gruplar,
                         pay_degeri=guncel_pay_degeri,
                         bakiye=bakiye)

@app.route('/hisseler')
def hisseler():
    hisseler_df = db.hisse_listele()
    return render_template('hisseler.html', hisseler=hisseler_df.to_dict('records'))

@app.route('/islemler')
def islemler():
    islemler_df = db.islem_listele()
    hisseler = db.hisse_listele()
    return render_template('islemler.html', islemler=islemler_df, hisseler=hisseler.to_dict('records'))

@app.route('/aylik_rapor')
def aylik_rapor():
    """Aylık raporu göster"""
    # Tarih parametrelerini al
    secili_yil = request.args.get('yil', datetime.now().year)
    secili_ay = request.args.get('ay', datetime.now().month)
    
    # Yıl ve ay listelerini oluştur
    yillar = range(2020, datetime.now().year + 1)
    aylar = range(1, 13)
    
    # Raporu al
    rapor = db.aylik_rapor(secili_yil, secili_ay)
    
    # Hisse işlemlerini al ve debug et
    islemler = db.aylik_islem_raporu(secili_yil, secili_ay)
    print(f"Aylık işlemler: {islemler.to_dict('records')}")  # Debug için
    
    return render_template('aylik_rapor.html',
                         rapor=rapor.to_dict('records'),
                         islemler=islemler.to_dict('records'),
                         yillar=yillar,
                         aylar=aylar,
                         secili_yil=int(secili_yil),
                         secili_ay=int(secili_ay))

@app.route('/islem_ekle', methods=['POST'])
def islem_ekle():
    data = request.get_json()
    # Debug için yazdıralım
    print("Gelen veri:", data)  # Gelen veriyi kontrol et
    
    sonuc = db.islem_ekle(
        sembol=data['sembol'],
        islem_tipi=data['islem_tipi'],
        miktar=int(data['miktar']),
        fiyat=float(data['fiyat']),
        grup_adi=data.get('grup_adi', ''),  # Boş string yerine None geliyorsa düzeltelim
        aciklama=data.get('aciklama', '')
    )
    return jsonify({'success': sonuc})

@app.route('/islem_gecmisi_temizle', methods=['POST'])
def islem_gecmisi_temizle():
    try:
        db.islem_gecmisi_temizle()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/hisse_bilgi/<sembol>')
def hisse_bilgi(sembol):
    try:
        hisse_verisi = yahoo_hisse_verisi_getir(sembol)
        
        if hisse_verisi:
            return jsonify({
                'success': True,
                'fiyat': float(hisse_verisi['price'])
            })
        
        return jsonify({
            'success': False,
            'message': 'Veri bulunamadı'
        })
            
    except Exception as e:
        print(f"Hata: {e}")
        return jsonify({
            'success': False,
            'message': 'Veri çekilirken hata oluştu'
        })

@app.route('/grafik/portfoy_dagilim')
def portfoy_dagilim_grafik():
    rapor = db.grup_raporu()
    
    if rapor.empty:
        return jsonify({
            'ana_grafik': json.dumps({
                'data': [{
                    'values': [],
                    'labels': [],
                    'type': 'pie'
                }],
                'layout': {'title': 'Portföy Dağılımı'}
            }),
            'grup_grafikleri': {}
        })
    
    # Ana grafik için grup toplamlarını hesapla
    grup_toplamlari = rapor.groupby('grup_adi')['grup_maliyet'].sum().reset_index()
    
    ana_grafik = {
        'data': [{
            'values': grup_toplamlari['grup_maliyet'].tolist(),
            'labels': grup_toplamlari['grup_adi'].tolist(),
            'type': 'pie'
        }],
        'layout': {
            'title': 'Portföy Dağılımı',
            'height': 400
        }
    }

    # Grup içi dağılım grafikleri
    grup_grafikleri = {}
    for grup in ['UZUN_VADE_1', 'UZUN_VADE_2', 'TRADE']:
        grup_verisi = rapor[rapor['grup_adi'] == grup]
        if not grup_verisi.empty:
            grup_grafikleri[grup] = json.dumps({
                'data': [{
                    'values': grup_verisi['grup_maliyet'].tolist(),
                    'labels': grup_verisi['sembol'].tolist(),
                    'type': 'pie'
                }],
                'layout': {
                    'title': f'{grup} Dağılımı',
                    'height': 400
                }
            })

    return jsonify({
        'ana_grafik': json.dumps(ana_grafik),
        'grup_grafikleri': grup_grafikleri
    })

@app.route('/canli_veri/<sembol>')
def canli_veri(sembol):
    """Hisse senedi için canlı veri getir"""
    try:
        hisse_verisi = yahoo_hisse_verisi_getir(sembol)
        
        if not hisse_verisi:
            return jsonify({
                'success': False,
                'message': 'Veriler henüz yüklenemedi'
            })
        
        return jsonify({
            'success': True,
            'data': {
                'sembol': sembol,
                'fiyat': float(hisse_verisi['price']),
                'degisim_yuzde': float(hisse_verisi['rate']),
                'hacim': int(hisse_verisi['volume']),
                'tarih': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'en_yuksek': float(hisse_verisi['previous']),
                'en_dusuk': float(hisse_verisi['previous'])
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        })

def yahoo_hisse_verisi_getir(sembol):
    """Yahoo Finance'den hisse verisi getir"""
    try:
        yahoo_sembol = f"{sembol}.IS"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_sembol}"
        
        # Her istek öncesi daha uzun bekleme
        time.sleep(3)
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 429:
            print("Rate limit aşıldı, 10 saniye bekleniyor...")
            time.sleep(10)
            response = requests.get(url, headers=headers, timeout=15)
            
        if response.status_code != 200:
            print(f"HTTP {response.status_code} for {url}")
            return None
            
        data = response.json()
        if data['chart']['result']:
            meta = data['chart']['result'][0]['meta']
            
            # Güvenli bir şekilde değerleri al, yoksa varsayılan değer kullan
            return {
                'code': sembol,
                'price': str(meta.get('regularMarketPrice', 0)),
                'rate': str(meta.get('regularMarketChangePercent', 0)),
                'volume': str(meta.get('regularMarketVolume', 0)),
                'previous': str(meta.get('previousClose', 0))
            }
        
        print(f"Veri bulunamadı: {yahoo_sembol}")
        return None
        
    except Exception as e:
        print(f"Yahoo veri çekme hatası ({sembol}): {e}")
        print(f"Tam yanıt: {response.text[:200]}")  # Yanıtı görelim
        return None

@app.route('/portfoy_guncelle')
def portfoy_guncelle():
    force = request.args.get('force', '0') == '1'
    try:
        portfoy_df = db.portfoy_raporu()
        guncel_veriler = []
        
        for _, hisse in portfoy_df.iterrows():
            sembol = hisse['sembol']
            hisse_verisi = yahoo_hisse_verisi_getir(sembol)
            
            if hisse_verisi:
                try:
                    guncel_fiyat = float(hisse_verisi['price'])
                    # Veritabanını güncelle
                    db.hisse_fiyat_guncelle(
                        sembol=sembol,
                        guncel_fiyat=guncel_fiyat
                    )
                    guncel_veriler.append({
                        'sembol': sembol,
                        'fiyat': guncel_fiyat
                    })
                except (KeyError, ValueError) as e:
                    print(f"Fiyat dönüşüm hatası ({sembol}): {e}")
                    continue
            else:
                print(f"Hisse verisi alınamadı: {sembol}")
        
        return jsonify({
            'success': True,
            'data': guncel_veriler
        })
    except Exception as e:
        print(f"Güncelleme hatası: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        })

@app.teardown_appcontext
def close_db(e=None):
    """Veritabanı bağlantısını kapat"""
    db = g.pop('db', None)
    if db is not None:
        conn = db.get_db()  # Önce bağlantıyı al
        db.close_db(conn)   # Sonra bağlantıyı kapat

@app.route('/gruplar')
def gruplar():
    df = db.grup_raporu()
    return render_template('gruplar.html', gruplar=df.to_dict('records'))

@app.route('/grup_ekle', methods=['POST'])
def grup_ekle():
    data = request.json
    sonuc = db.grup_ekle(
        grup_adi=data['grup_adi'],
        hedef_oran=data['hedef_oran'],
        aciklama=data.get('aciklama')
    )
    return jsonify({'success': sonuc})

@app.route('/hisse_gruba_ekle', methods=['POST'])
def hisse_gruba_ekle():
    data = request.json
    sonuc = db.hisse_gruba_ekle(data['sembol'], data['grup_adi'])
    return jsonify({'success': sonuc})

@app.route('/bist_hisseleri_ekle')
def bist_hisseleri_yukle():
    """BIST hisselerini veritabanına ekle"""
    eklenen_hisseler = db.bist_hisseleri_ekle()
    return jsonify({
        'success': True,
        'message': f'Toplam {len(eklenen_hisseler)} hisse eklendi',
        'hisseler': eklenen_hisseler
    })

@app.route('/musteriler')
def musteriler():
    """Müşteriler sayfasını göster"""
    musteri_listesi = db.musteri_listesi()
    return render_template('musteriler.html', musteriler=musteri_listesi.to_dict('records'))

@app.route('/musteri/<int:musteri_id>')
def musteri_bilgileri(musteri_id):
    """Müşteri detay sayfasını göster"""
    musteri_listesi = db.musteri_listesi()
    musteri = musteri_listesi[musteri_listesi['id'] == musteri_id].iloc[0].to_dict()
    
    # Müşterinin işlem geçmişini al
    islemler = db.musteri_islem_gecmisi(musteri_id)
    
    return render_template('musteri_bilgileri.html', 
                         musteri=musteri,
                         islemler=islemler.to_dict('records'))

@app.route('/musteri_yatirim_ekle', methods=['POST'])
def musteri_yatirim_ekle():
    """Müşteri yatırım/çekim işlemi ekle"""
    data = request.get_json()
    sonuc = db.musteri_yatirim_ekle(
        musteri_id=data['musteri_id'],
        miktar=float(data['miktar']),
        islem_tipi=data['islem_tipi'],
        aciklama=data.get('aciklama')
    )
    return jsonify({'success': sonuc})

@app.route('/musteri_sil/<int:musteri_id>', methods=['POST'])
def musteri_sil(musteri_id):
    """Müşteriyi sil"""
    sonuc = db.musteri_sil(musteri_id)
    return jsonify({'success': sonuc})

@app.route('/musteri_ekle', methods=['POST'])
def musteri_ekle():
    """Yeni müşteri ekle"""
    try:
        data = request.get_json()
        musteri_id = db.musteri_ekle(
            ad_soyad=data['ad_soyad'],
            telefon=data.get('telefon'),
            email=data.get('email')
        )
        
        if musteri_id:
            return jsonify({
                'success': True,
                'musteri_id': musteri_id
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Müşteri eklenirken bir hata oluştu'
            })
            
    except Exception as e:
        print(f"Müşteri ekleme hatası: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 400

if __name__ == '__main__':
    app.run(debug=True)