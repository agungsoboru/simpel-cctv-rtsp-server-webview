# simpel-cctv-rtsp-server-webview
Simple Python-based multi-camera CCTV system that streams RTSP cameras from multiple clients to a central web server. Supports multiple locations, configurable FPS/JPEG quality/resolution, automatic client reconnect, and browser-based CCTV monitoring without requiring the Hikvision application.

![CCTV Web View](gambar.jpg)

### Description

> Simple Python-based multi-camera CCTV system that streams RTSP cameras from multiple clients to a central web server. Supports multiple locations, configurable FPS/JPEG quality/resolution, automatic client reconnect, and browser-based CCTV monitoring without requiring the Hikvision application.

### README singkat


# Simpel CCTV RTSP Server WebView

Simple project untuk memantau banyak kamera CCTV RTSP dari berbagai lokasi melalui web browser.

Project ini terdiri dari:

- `client.py` — mengambil stream dari kamera RTSP dan mengirim frame ke server.
- `server.py` — menerima frame dari banyak client dan menampilkannya dalam satu halaman web.
- `konfigurasi.conf` — konfigurasi server, lokasi, kamera, FPS, kualitas JPEG, dan resolusi.

## Fitur

- Multi-camera
- Multi-client / multi-location
- Kamera RTSP
- Monitoring melalui web browser
- Nama kamera dan lokasi dapat dikonfigurasi
- Otomatis menambahkan kamera ketika client baru terhubung
- Grid otomatis menyesuaikan jumlah kamera
- Pengaturan FPS
- Pengaturan kualitas JPEG
- Pengaturan resolusi maksimum
- Mengurangi penggunaan bandwidth
- Client tetap berjalan ketika koneksi server terputus
- Automatic reconnect
- Reconnect dengan interval 20 detik
- Streaming hanya aktif ketika web viewer sedang digunakan
- Tidak membutuhkan aplikasi CCTV khusus seperti Hikvision

## Konfigurasi

Contoh:

```conf
[SERVER]
host = 103.175.217.23
port = 9090

[LOCATION]
name = padangbai

[NETWORK]
jpeg_quality = 40
max_width = 640
fps = 3
reconnect_delay = 20

[CAMERA_1]
name = Pintu Depan
rtsp = rtsp://user:password@192.168.1.100:554/Streaming/Channels/101

[CAMERA_2]
name = Pintu Keluar
rtsp = rtsp://user:password@192.168.1.101:554/Streaming/Channels/101
````

## Menjalankan Client

```bash
python3 client.py
```

## Menjalankan Server

```bash
python3 server.py
```

Kemudian buka:

```text
http://SERVER-IP:9191
```

Password default:

```text
1234
```

## Catatan

Project ini dibuat sebagai project sederhana/eksperimen untuk monitoring CCTV RTSP melalui web browser dan bukan sebagai sistem CCTV production-grade.




