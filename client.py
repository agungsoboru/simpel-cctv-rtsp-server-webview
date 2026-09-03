import cv2
import socket
import struct
import json
import threading
import time
import configparser
import os
import sys


# ============================================================
# CONFIG
# ============================================================

CONFIG_FILE = "configurasi.conf"

RECONNECT_DELAY = 20

sock = None
sock_lock = threading.Lock()

running = True
streaming = False

connected_event = threading.Event()
connection_lost_event = threading.Event()


# ============================================================
# READ CONFIG
# ============================================================

config = configparser.ConfigParser()

config_path = os.path.join(
    os.path.dirname(
        os.path.abspath(__file__)
    ),
    CONFIG_FILE
)

if not config.read(
    config_path,
    encoding="utf-8"
):
    print(
        "ERROR: konfigurasi.conf tidak ditemukan:",
        config_path
    )
    sys.exit(1)


SERVER_HOST = config["SERVER"]["host"]

SERVER_PORT = config.getint(
    "SERVER",
    "port",
    fallback=9090
)

LOCATION = config["LOCATION"]["name"]

JPEG_QUALITY = config.getint(
    "NETWORK",
    "jpeg_quality",
    fallback=40
)

MAX_WIDTH = config.getint(
    "NETWORK",
    "max_width",
    fallback=640
)

FPS = config.getfloat(
    "NETWORK",
    "fps",
    fallback=3
)

RECONNECT_DELAY = config.getint(
    "NETWORK",
    "reconnect_delay",
    fallback=20
)


# ============================================================
# CAMERA CONFIG
# ============================================================

cameras = []

for section in config.sections():

    if not section.startswith("CAMERA_"):
        continue

    camera_id = section

    camera_name = config[section].get(
        "name",
        section
    )

    rtsp = config[section].get(
        "rtsp",
        ""
    )

    if not rtsp:
        continue

    cameras.append(
        {
            "id": camera_id,
            "name": camera_name,
            "rtsp": rtsp
        }
    )


# ============================================================
# INFO
# ============================================================

print()
print("======================================")
print("           CCTV CLIENT")
print("======================================")
print("Location       :", LOCATION)
print("Server         :", SERVER_HOST)
print("Server Port    :", SERVER_PORT)
print("FPS            :", FPS)
print("Max Width      :", MAX_WIDTH)
print("JPEG Quality   :", JPEG_QUALITY)
print("Reconnect Delay:", RECONNECT_DELAY)
print("======================================")
print()

print("Cameras:")

for camera in cameras:

    print(
        " ",
        camera["id"],
        camera["name"]
    )

print()


# ============================================================
# RECEIVE EXACT
# ============================================================

def recv_exact(
    connection,
    size
):

    data = b""

    while len(data) < size:

        chunk = connection.recv(
            size - len(data)
        )

        if not chunk:

            raise ConnectionError(
                "Server disconnected"
            )

        data += chunk

    return data


# ============================================================
# RECEIVE PACKET
# ============================================================

def recv_packet(
    connection
):

    raw = recv_exact(
        connection,
        4
    )

    packet_size = struct.unpack(
        "!I",
        raw
    )[0]

    if packet_size > 20 * 1024 * 1024:

        raise ValueError(
            "Packet terlalu besar"
        )

    packet = recv_exact(
        connection,
        packet_size
    )

    if len(packet) < 5:

        raise ValueError(
            "Packet tidak valid"
        )

    packet_type = packet[0]

    metadata_size = struct.unpack(
        "!I",
        packet[1:5]
    )[0]

    if (
        5 + metadata_size
        >
        len(packet)
    ):

        raise ValueError(
            "Metadata tidak valid"
        )

    metadata_raw = packet[
        5:
        5 + metadata_size
    ]

    metadata = json.loads(
        metadata_raw.decode(
            "utf-8"
        )
    )

    payload = packet[
        5 + metadata_size:
    ]

    return (
        packet_type,
        metadata,
        payload
    )


# ============================================================
# SEND PACKET
# ============================================================

def send_packet(
    packet_type,
    metadata=None,
    payload=b""
):

    global sock

    if metadata is None:

        metadata = {}

    metadata_raw = json.dumps(
        metadata
    ).encode(
        "utf-8"
    )

    packet = (
        bytes([packet_type])
        +
        struct.pack(
            "!I",
            len(metadata_raw)
        )
        +
        metadata_raw
        +
        payload
    )

    with sock_lock:

        current_sock = sock

        if current_sock is None:

            raise ConnectionError(
                "Socket tidak tersedia"
            )

        current_sock.sendall(
            struct.pack(
                "!I",
                len(packet)
            )
        )

        current_sock.sendall(
            packet
        )


# ============================================================
# CLOSE SOCKET
# ============================================================

def close_socket():

    global sock

    with sock_lock:

        old_sock = sock

        sock = None

    connected_event.clear()

    if old_sock is not None:

        try:

            old_sock.shutdown(
                socket.SHUT_RDWR
            )

        except Exception:

            pass

        try:

            old_sock.close()

        except Exception:

            pass


# ============================================================
# CONNECT SERVER
# ============================================================

def connect_server():

    global sock

    while running:

        new_sock = None

        try:

            print(
                "Connecting to server..."
            )

            new_sock = socket.socket(
                socket.AF_INET,
                socket.SOCK_STREAM
            )

            new_sock.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_KEEPALIVE,
                1
            )

            new_sock.settimeout(
                15
            )

            new_sock.connect(
                (
                    SERVER_HOST,
                    SERVER_PORT
                )
            )

            new_sock.settimeout(
                None
            )

            with sock_lock:

                sock = new_sock

            print(
                "Connected to server"
            )

            # ------------------------------------------------
            # HELLO
            # ------------------------------------------------

            send_packet(
                1,
                {
                    "location": LOCATION,

                    "cameras": [

                        {
                            "id": camera["id"],
                            "name": camera["name"]
                        }

                        for camera in cameras

                    ]
                }
            )

            # ------------------------------------------------
            # SERVER ACCEPT
            # ------------------------------------------------

            packet_type, metadata, payload = recv_packet(
                new_sock
            )

            if (
                packet_type != 3
                or
                metadata.get("status") != "OK"
            ):

                raise ConnectionError(
                    "Server tidak menerima client"
                )

            print(
                "Server accepted client"
            )

            connected_event.set()

            return new_sock

        except Exception as e:

            print(
                "Connection failed:",
                e
            )

            if new_sock is not None:

                try:

                    new_sock.close()

                except Exception:

                    pass

            with sock_lock:

                if sock is new_sock:

                    sock = None

            connected_event.clear()

            if running:

                print(
                    "Retry dalam",
                    RECONNECT_DELAY,
                    "detik..."
                )

                time.sleep(
                    RECONNECT_DELAY
                )

    return None


# ============================================================
# SERVER COMMAND LISTENER
# ============================================================

def command_listener(
    connection
):

    global streaming

    try:

        while (
            running
            and
            connected_event.is_set()
        ):

            packet_type, metadata, payload = recv_packet(
                connection
            )

            if packet_type != 2:

                continue

            command = metadata.get(
                "command"
            )

            if command == "START":

                print(
                    "Server meminta START"
                )

                streaming = True

            elif command == "STOP":

                print(
                    "Server meminta STOP"
                )

                streaming = False

    except (
        ConnectionResetError,
        ConnectionAbortedError,
        BrokenPipeError,
        ConnectionError,
        OSError
    ) as e:

        if running:

            print(
                "Server connection lost:",
                e
            )

    except Exception as e:

        if running:

            print(
                "Command listener error:",
                e
            )

    finally:

        streaming = False

        connection_lost_event.set()

        connected_event.clear()

        try:

            connection.shutdown(
                socket.SHUT_RDWR
            )

        except Exception:

            pass

        try:

            connection.close()

        except Exception:

            pass


# ============================================================
# CAMERA WORKER
# ============================================================

def camera_worker(
    camera
):

    global running
    global streaming

    cap = None

    frame_interval = (
        1.0 /
        max(
            FPS,
            0.1
        )
    )

    last_send = 0

    while running:

        # ====================================================
        # SERVER DISCONNECTED
        # ====================================================

        if not connected_event.is_set():

            if cap is not None:

                try:

                    cap.release()

                except Exception:

                    pass

                cap = None

            time.sleep(1)

            continue


        # ====================================================
        # NO VIEWER
        # ====================================================

        if not streaming:

            if cap is not None:

                print(
                    "Stopping RTSP:",
                    camera["name"]
                )

                try:

                    cap.release()

                except Exception:

                    pass

                cap = None

            time.sleep(1)

            continue


        # ====================================================
        # OPEN RTSP
        # ====================================================

        if cap is None:

            print(
                "Opening RTSP:",
                camera["name"]
            )

            try:

                cap = cv2.VideoCapture(
                    camera["rtsp"],
                    cv2.CAP_FFMPEG
                )

                try:

                    cap.set(
                        cv2.CAP_PROP_BUFFERSIZE,
                        1
                    )

                except Exception:

                    pass

            except Exception as e:

                print(
                    "RTSP open error:",
                    camera["name"],
                    e
                )

                cap = None


            if (
                cap is None
                or
                not cap.isOpened()
            ):

                print(
                    "RTSP gagal:",
                    camera["name"]
                )

                if cap is not None:

                    try:

                        cap.release()

                    except Exception:

                        pass

                cap = None

                time.sleep(3)

                continue


        # ====================================================
        # READ FRAME
        # ====================================================

        try:

            ok, frame = cap.read()

        except (
            ConnectionResetError,
            BrokenPipeError,
            ConnectionError,
            OSError
        ) as e:

            print(
                "RTSP connection error:",
                camera["name"],
                e
            )

            ok = False
            frame = None

        except Exception as e:

            print(
                "RTSP read error:",
                camera["name"],
                e
            )

            ok = False
            frame = None


        if not ok or frame is None:

            print(
                "RTSP disconnected:",
                camera["name"]
            )

            try:

                cap.release()

            except Exception:

                pass

            cap = None

            time.sleep(3)

            continue


        # ====================================================
        # FPS LIMIT
        # ====================================================

        now = time.time()

        if (
            now - last_send
            <
            frame_interval
        ):

            continue

        last_send = now


        # ====================================================
        # RESIZE
        # ====================================================

        try:

            height, width = frame.shape[:2]

            if width > MAX_WIDTH:

                scale = (
                    MAX_WIDTH /
                    float(width)
                )

                new_width = int(
                    width * scale
                )

                new_height = int(
                    height * scale
                )

                frame = cv2.resize(
                    frame,
                    (
                        new_width,
                        new_height
                    ),
                    interpolation=cv2.INTER_AREA
                )

        except Exception as e:

            print(
                "Resize error:",
                camera["name"],
                e
            )

            continue


        # ====================================================
        # JPEG
        # ====================================================

        try:

            ok, encoded = cv2.imencode(
                ".jpg",
                frame,
                [
                    cv2.IMWRITE_JPEG_QUALITY,
                    JPEG_QUALITY
                ]
            )

        except Exception as e:

            print(
                "JPEG encode error:",
                camera["name"],
                e
            )

            continue


        if not ok:

            continue


        jpeg = encoded.tobytes()


        # ====================================================
        # SEND
        # ====================================================

        try:

            send_packet(
                10,
                {
                    "camera_id":
                        camera["id"]
                },
                jpeg
            )

        except (
            ConnectionResetError,
            ConnectionAbortedError,
            BrokenPipeError,
            ConnectionError,
            OSError
        ) as e:

            print(
                "Send error:",
                e
            )

            # Jangan pernah set running=False
            # karena error jaringan.
            #
            # Program harus tetap hidup dan
            # melakukan reconnect.

            streaming = False

            connection_lost_event.set()

            connected_event.clear()

            if cap is not None:

                try:

                    cap.release()

                except Exception:

                    pass

                cap = None

            time.sleep(1)

        except Exception as e:

            print(
                "Send error:",
                e
            )

            streaming = False

            connection_lost_event.set()

            connected_event.clear()

            if cap is not None:

                try:

                    cap.release()

                except Exception:

                    pass

                cap = None

            time.sleep(1)


    # ========================================================
    # CLEANUP
    # ========================================================

    if cap is not None:

        try:

            cap.release()

        except Exception:

            pass


# ============================================================
# PING WORKER
# ============================================================

def ping_worker(
    connection
):

    global running

    try:

        while (
            running
            and
            connected_event.is_set()
        ):

            time.sleep(5)

            if not connected_event.is_set():

                break

            try:

                send_packet(
                    20,
                    {
                        "time":
                            time.time()
                    }
                )

            except (
                ConnectionResetError,
                ConnectionAbortedError,
                BrokenPipeError,
                ConnectionError,
                OSError
            ) as e:

                print(
                    "Ping error:",
                    e
                )

                connection_lost_event.set()

                connected_event.clear()

                break

    except Exception as e:

        if running:

            print(
                "Ping worker error:",
                e
            )

        connection_lost_event.set()

        connected_event.clear()


# ============================================================
# MAIN
# ============================================================

def main():

    global running
    global streaming

    # ========================================================
    # CAMERA THREADS
    # ========================================================

    for camera in cameras:

        thread = threading.Thread(
            target=camera_worker,
            args=(camera,),
            daemon=True
        )

        thread.start()


    # ========================================================
    # CONNECTION LOOP
    # ========================================================

    while running:

        connection_lost_event.clear()

        streaming = False


        # ----------------------------------------------------
        # CONNECT
        # ----------------------------------------------------

        connection = connect_server()

        if connection is None:

            continue


        # ----------------------------------------------------
        # COMMAND LISTENER
        # ----------------------------------------------------

        listener = threading.Thread(
            target=command_listener,
            args=(connection,),
            daemon=True
        )

        listener.start()


        # ----------------------------------------------------
        # PING
        # ----------------------------------------------------

        ping = threading.Thread(
            target=ping_worker,
            args=(connection,),
            daemon=True
        )

        ping.start()


        # ----------------------------------------------------
        # WAIT CONNECTION
        # ----------------------------------------------------

        while (
            running
            and
            connected_event.is_set()
            and
            not connection_lost_event.is_set()
        ):

            time.sleep(1)


        if not running:

            break


        # ----------------------------------------------------
        # CONNECTION LOST
        # ----------------------------------------------------

        streaming = False

        connected_event.clear()

        close_socket()

        print()
        print(
            "======================================"
        )
        print(
            "SERVER CONNECTION LOST"
        )
        print(
            "Program tetap berjalan."
        )
        print(
            "Reconnect dalam",
            RECONNECT_DELAY,
            "detik..."
        )
        print(
            "======================================"
        )
        print()


        # ====================================================
        # WAJIB TUNGGU 20 DETIK
        # ====================================================

        time.sleep(
            RECONNECT_DELAY
        )


    # ========================================================
    # CLEANUP
    # ========================================================

    running = False

    streaming = False

    connected_event.clear()

    close_socket()

    print(
        "Client stopped."
    )


# ============================================================
# CTRL+C
# ============================================================

try:

    main()

except KeyboardInterrupt:

    print()
    print(
        "Stopping..."
    )

    running = False

    streaming = False

    connected_event.clear()

    close_socket()

    time.sleep(1)
