import socket
import struct
import json
import threading
import time

from flask import (
    Flask,
    Response,
    request,
    session,
    redirect,
    render_template_string,
    jsonify
)


# ============================================================
# CONFIG
# ============================================================

HOST = "0.0.0.0"

CLIENT_PORT = 9090

WEB_PORT = 9191

PASSWORD = "12345678"

# Browser dianggap masih aktif jika heartbeat
# diterima dalam waktu ini.
VIEWER_TIMEOUT = 5


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)

app.secret_key = "cctv-server-secret-key"


# ============================================================
# CAMERA
# ============================================================

cameras = {}

cameras_lock = threading.Lock()


class Camera:

    def __init__(
        self,
        camera_id,
        location,
        name,
        client_socket
    ):

        self.camera_id = camera_id
        self.location = location
        self.name = name
        self.client_socket = client_socket

        self.frame = None
        self.frame_number = 0

        self.streaming_requested = False
        self.last_seen = time.time()

        self.lock = threading.Lock()

    def set_frame(self, frame):

        with self.lock:

            self.frame = frame
            self.frame_number += 1
            self.last_seen = time.time()

    def get_frame(self):

        with self.lock:
            return self.frame


# ============================================================
# VIEWERS
# ============================================================

viewers = {}

viewers_lock = threading.Lock()


def viewer_is_active():

    now = time.time()

    with viewers_lock:

        expired = []

        for viewer_id, last_time in viewers.items():

            if now - last_time > VIEWER_TIMEOUT:

                expired.append(viewer_id)

        for viewer_id in expired:

            del viewers[viewer_id]

        return len(viewers) > 0


# ============================================================
# NETWORK
# ============================================================

def recv_exact(sock, size):

    data = b""

    while len(data) < size:

        chunk = sock.recv(
            size - len(data)
        )

        if not chunk:

            raise ConnectionError(
                "Connection closed"
            )

        data += chunk

    return data


def recv_packet(sock):

    raw = recv_exact(
        sock,
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
        sock,
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

    if 5 + metadata_size > len(packet):

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


def send_packet(
    sock,
    packet_type,
    metadata=None,
    payload=b""
):

    if metadata is None:

        metadata = {}

    metadata_raw = json.dumps(
        metadata
    ).encode("utf-8")

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

    sock.sendall(
        struct.pack(
            "!I",
            len(packet)
        )
    )

    sock.sendall(packet)


def send_command(
    sock,
    command
):

    try:

        send_packet(
            sock,
            2,
            {
                "command": command
            }
        )

        return True

    except Exception as e:

        print(
            "Command error:",
            e
        )

        return False


# ============================================================
# REMOVE CLIENT
# ============================================================

def remove_client(sock):

    with cameras_lock:

        remove_ids = []

        for camera_id, camera in cameras.items():

            if camera.client_socket is sock:

                remove_ids.append(
                    camera_id
                )

        for camera_id in remove_ids:

            camera = cameras.pop(
                camera_id,
                None
            )

            if camera:

                print(
                    "Camera offline:",
                    camera.location,
                    "-",
                    camera.name
                )


# ============================================================
# CLIENT HANDLER
# ============================================================

def client_handler(
    sock,
    address
):

    print(
        "Client connected:",
        address
    )

    try:

        packet_type, metadata, payload = recv_packet(
            sock
        )

        if packet_type != 1:

            raise ValueError(
                "HELLO packet expected"
            )

        location = metadata.get(
            "location",
            "Unknown"
        )

        camera_list = metadata.get(
            "cameras",
            []
        )

        print(
            "Location:",
            location
        )

        for cam in camera_list:

            camera_id = cam.get(
                "id"
            )

            camera_name = cam.get(
                "name",
                camera_id
            )

            if not camera_id:

                continue

            camera = Camera(
                camera_id,
                location,
                camera_name,
                sock
            )

            with cameras_lock:

                cameras[camera_id] = camera

            print(
                "Registered:",
                camera_id,
                "-",
                location,
                "-",
                camera_name
            )

        send_packet(
            sock,
            3,
            {
                "status": "OK"
            }
        )

        while True:

            packet_type, metadata, payload = recv_packet(
                sock
            )

            # ------------------------------------------------
            # FRAME
            # ------------------------------------------------

            if packet_type == 10:

                camera_id = metadata.get(
                    "camera_id"
                )

                if not camera_id:

                    continue

                with cameras_lock:

                    camera = cameras.get(
                        camera_id
                    )

                if camera:

                    camera.set_frame(
                        payload
                    )

            # ------------------------------------------------
            # PING
            # ------------------------------------------------

            elif packet_type == 20:

                pass

    except Exception as e:

        print(
            "Client disconnected:",
            address,
            "-",
            e
        )

    finally:

        remove_client(
            sock
        )

        try:

            sock.close()

        except Exception:

            pass


# ============================================================
# TCP SERVER
# ============================================================

def client_server():

    server = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    )

    server.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_REUSEADDR,
        1
    )

    server.bind(
        (
            HOST,
            CLIENT_PORT
        )
    )

    server.listen(100)

    print(
        "======================================"
    )

    print(
        "CCTV CLIENT SERVER"
    )

    print(
        f"TCP Port : {CLIENT_PORT}"
    )

    print(
        "======================================"
    )

    while True:

        try:

            sock, address = server.accept()

            thread = threading.Thread(
                target=client_handler,
                args=(
                    sock,
                    address
                ),
                daemon=True
            )

            thread.start()

        except Exception as e:

            print(
                "Accept error:",
                e
            )


# ============================================================
# STREAM MONITOR
# ============================================================

def stream_monitor():

    while True:

        active = viewer_is_active()

        with cameras_lock:

            camera_list = list(
                cameras.values()
            )

        for camera in camera_list:

            # =================================================
            # ADA ORANG MELIHAT WEB
            # =================================================

            if active:

                if not camera.streaming_requested:

                    print(
                        "START:",
                        camera.location,
                        "-",
                        camera.name
                    )

                    success = send_command(
                        camera.client_socket,
                        "START"
                    )

                    if success:

                        camera.streaming_requested = True


            # =================================================
            # TIDAK ADA YANG MELIHAT WEB
            # =================================================

            else:

                if camera.streaming_requested:

                    print(
                        "STOP:",
                        camera.location,
                        "-",
                        camera.name
                    )

                    success = send_command(
                        camera.client_socket,
                        "STOP"
                    )

                    if success:

                        camera.streaming_requested = False


        time.sleep(1)
# ============================================================
# LOGIN PAGE
# ============================================================

LOGIN_HTML = """
<!DOCTYPE html>

<html>

<head>

<meta
    name="viewport"
    content="width=device-width, initial-scale=1"
>

<title>CCTV Login</title>

<style>

body {

    margin: 0;

    background: #111;

    color: white;

    font-family: Arial;

    text-align: center;
}

.login {

    width: 320px;

    max-width: 90%;

    margin: 120px auto;
}

input {

    width: 100%;

    padding: 13px;

    box-sizing: border-box;

    font-size: 17px;

    margin-bottom: 10px;
}

button {

    width: 100%;

    padding: 13px;

    font-size: 17px;

    cursor: pointer;
}

.error {

    color: #ff5555;
}

</style>

</head>

<body>

<div class="login">

<h2>CCTV SERVER</h2>

<form method="post">

<input
    type="password"
    name="password"
    placeholder="Password"
    autofocus
>

<button type="submit">
LOGIN
</button>

</form>

{% if error %}

<p class="error">
Password salah
</p>

{% endif %}

</div>

</body>

</html>
"""


# ============================================================
# LOGIN
# ============================================================

@app.route(
    "/login",
    methods=[
        "GET",
        "POST"
    ]
)
def login():

    if request.method == "POST":

        password = request.form.get(
            "password",
            ""
        )

        if password == PASSWORD:

            session["logged_in"] = True

            return redirect("/")

        return render_template_string(
            LOGIN_HTML,
            error=True
        )

    return render_template_string(
        LOGIN_HTML,
        error=False
    )


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/login")


# ============================================================
# MAIN WEB
# ============================================================

HTML = """
<!DOCTYPE html>

<html>

<head>

<meta
    name="viewport"
    content="width=device-width, initial-scale=1"
>

<title>CCTV Server</title>

<style>

* {
    box-sizing: border-box;
}

body {

    margin: 0;

    background: #111;

    color: white;

    font-family: Arial, sans-serif;
}

.header {

    height: 55px;

    padding: 0 15px;

    background: #222;

    display: flex;

    align-items: center;

    justify-content: space-between;

    position: sticky;

    top: 0;

    z-index: 100;
}

.header a {

    color: white;

    text-decoration: none;
}

.grid {

    display: grid;

    grid-template-columns:
        repeat(
            auto-fit,
            minmax(
                320px,
                1fr
            )
        );

    gap: 8px;

    padding: 8px;
}

.camera {

    background: #222;

    border-radius: 5px;

    overflow: hidden;

    min-width: 0;
}

.camera-title {

    min-height: 40px;

    padding: 10px;

    background: #333;

    font-size: 14px;

    white-space: nowrap;

    overflow: hidden;

    text-overflow: ellipsis;
}

.video-container {

    position: relative;

    width: 100%;

    aspect-ratio: 16 / 9;

    background: #000;
}

.video-container img {

    position: absolute;

    left: 0;

    top: 0;

    width: 100%;

    height: 100%;

    object-fit: contain;

    display: block;
}

.status {

    position: absolute;

    left: 8px;

    bottom: 8px;

    padding: 5px 8px;

    background: rgba(
        0,
        0,
        0,
        0.75
    );

    border-radius: 4px;

    font-size: 11px;
}

</style>

</head>

<body>


<div class="header">

<div>
<b>CCTV SERVER</b>
</div>

<div>
<a href="/logout">
Logout
</a>
</div>

</div>


<div
    id="camera-grid"
    class="grid"
>
</div>


<script>

const cameraGrid =
    document.getElementById(
        "camera-grid"
    );


const cameras = {};

const frameTimers = {};

const frameBusy = {};

const lastFrameUrl = {};


const FRAME_INTERVAL = 300;


// ============================================================
// CREATE CAMERA
// ============================================================

function createCamera(camera) {

    if (
        document.getElementById(
            "camera-" +
            camera.camera_id
        )
    ) {

        return;
    }


    const box =
        document.createElement(
            "div"
        );


    box.className = "camera";


    box.id =
        "camera-" +
        camera.camera_id;


    const safeId =
        camera.camera_id.replace(
            /[^a-zA-Z0-9_-]/g,
            "_"
        );


    box.innerHTML = `

        <div class="camera-title">

            ${escapeHtml(camera.location)}

            -

            ${escapeHtml(camera.name)}

        </div>


        <div class="video-container">

            <img
                id="img-${safeId}"
                alt=""
            >

            <div
                class="status"
                id="status-${safeId}"
            >
                WAITING
            </div>

        </div>

    `;


    cameraGrid.appendChild(
        box
    );


    cameras[
        camera.camera_id
    ] = true;


    frameBusy[
        camera.camera_id
    ] = false;


    updateFrame(
        camera.camera_id,
        safeId
    );
}


// ============================================================
// REMOVE CAMERA
// ============================================================

function removeCamera(
    cameraId
) {

    const element =
        document.getElementById(
            "camera-" +
            cameraId
        );


    if (element) {

        element.remove();

    }


    cameras[
        cameraId
    ] = false;


    if (
        frameTimers[cameraId]
    ) {

        clearTimeout(
            frameTimers[cameraId]
        );

    }


    if (
        lastFrameUrl[cameraId]
    ) {

        URL.revokeObjectURL(
            lastFrameUrl[cameraId]
        );

        delete lastFrameUrl[
            cameraId
        ];

    }


    delete frameBusy[
        cameraId
    ];
}


// ============================================================
// CAMERA LIST
// ============================================================

async function loadCameraList() {

    try {

        const response =
            await fetch(
                "/api/cameras",
                {
                    cache:
                        "no-store"
                }
            );


        if (
            !response.ok
        ) {

            return;

        }


        const list =
            await response.json();


        const currentIds =
            new Set();


        for (
            const camera
            of list
        ) {

            currentIds.add(
                camera.camera_id
            );

            createCamera(
                camera
            );

        }


        for (
            const id
            in cameras
        ) {

            if (
                !currentIds.has(id)
            ) {

                removeCamera(
                    id
                );

            }

        }


    } catch (error) {

        console.log(
            "Camera list error:",
            error
        );

    }

}


// ============================================================
// FRAME
// ============================================================

async function updateFrame(
    cameraId,
    safeId
) {

    if (
        !cameras[cameraId]
    ) {

        return;

    }


    if (
        frameBusy[cameraId]
    ) {

        scheduleNextFrame(
            cameraId,
            safeId
        );

        return;

    }


    frameBusy[
        cameraId
    ] = true;


    try {

        const response =
            await fetch(

                "/frame/" +

                encodeURIComponent(
                    cameraId
                ) +

                "?t=" +

                Date.now(),

                {
                    cache:
                        "no-store"
                }

            );


        if (
            response.status === 200
        ) {

            const blob =
                await response.blob();


            const newUrl =
                URL.createObjectURL(
                    blob
                );


            const img =
                document.getElementById(
                    "img-" +
                    safeId
                );


            const status =
                document.getElementById(
                    "status-" +
                    safeId
                );


            if (img) {

                const oldUrl =
                    lastFrameUrl[
                        cameraId
                    ];


                img.src =
                    newUrl;


                lastFrameUrl[
                    cameraId
                ] =
                    newUrl;


                if (oldUrl) {

                    URL.revokeObjectURL(
                        oldUrl
                    );

                }


                if (status) {

                    status.textContent =
                        "LIVE";

                }

            } else {

                URL.revokeObjectURL(
                    newUrl
                );

            }

        } else {

            const status =
                document.getElementById(
                    "status-" +
                    safeId
                );


            if (status) {

                status.textContent =
                    "WAITING";

            }

        }

    } catch (error) {

        const status =
            document.getElementById(
                "status-" +
                safeId
            );


        if (status) {

            status.textContent =
                "OFFLINE";

        }

    }


    frameBusy[
        cameraId
    ] = false;


    scheduleNextFrame(
        cameraId,
        safeId
    );
}


// ============================================================
// FRAME TIMER
// ============================================================

function scheduleNextFrame(
    cameraId,
    safeId
) {

    if (
        !cameras[cameraId]
    ) {

        return;

    }


    frameTimers[
        cameraId
    ] = setTimeout(

        function() {

            updateFrame(
                cameraId,
                safeId
            );

        },

        FRAME_INTERVAL

    );

}


// ============================================================
// ESCAPE HTML
// ============================================================

function escapeHtml(text) {

    const div =
        document.createElement(
            "div"
        );

    div.textContent =
        text;

    return div.innerHTML;
}


// ============================================================
// VIEWER HEARTBEAT
// ============================================================

async function heartbeat() {

    try {

        await fetch(
            "/api/heartbeat",
            {
                method: "POST",
                cache: "no-store"
            }
        );

    } catch (error) {

        console.log(
            "Heartbeat error:",
            error
        );

    }

}


// ============================================================
// START
// ============================================================

loadCameraList();

heartbeat();


// Cek kamera baru setiap 3 detik

setInterval(
    loadCameraList,
    3000
);


// Beritahu server browser masih aktif

setInterval(
    heartbeat,
    2000
);


</script>


</body>

</html>
"""


# ============================================================
# INDEX
# ============================================================

@app.route("/")
def index():

    if not session.get(
        "logged_in"
    ):

        return redirect(
            "/login"
        )

    return render_template_string(
        HTML
    )


# ============================================================
# HEARTBEAT
# ============================================================

@app.route(
    "/api/heartbeat",
    methods=["POST"]
)
def heartbeat():

    if not session.get(
        "logged_in"
    ):

        return jsonify(
            {
                "error":
                    "Unauthorized"
            }
        ), 401


    viewer_id = session.get(
        "viewer_id"
    )


    if not viewer_id:

        viewer_id = (
            str(
                request.remote_addr
            )
            +
            "-"
            +
            str(
                id(session)
            )
        )

        session[
            "viewer_id"
        ] = viewer_id


    with viewers_lock:

        viewers[
            viewer_id
        ] = time.time()


    return jsonify(
        {
            "status":
                "ok"
        }
    )


# ============================================================
# CAMERA API
# ============================================================

@app.route(
    "/api/cameras"
)
def api_cameras():

    if not session.get(
        "logged_in"
    ):

        return jsonify(
            {
                "error":
                    "Unauthorized"
            }
        ), 401


    with cameras_lock:

        result = []


        for camera in cameras.values():

            result.append(
                {
                    "camera_id":
                        camera.camera_id,

                    "location":
                        camera.location,

                    "name":
                        camera.name
                }
            )


    return jsonify(
        result
    )


# ============================================================
# FRAME
# ============================================================

@app.route(
    "/frame/<camera_id>"
)
def get_frame(camera_id):

    if not session.get(
        "logged_in"
    ):

        return (
            "Unauthorized",
            401
        )


    with cameras_lock:

        camera = cameras.get(
            camera_id
        )


    if not camera:

        return (
            "Camera tidak ditemukan",
            404
        )


    frame = camera.get_frame()


    if frame is None:

        return Response(
            status=204
        )


    return Response(

        frame,

        mimetype="image/jpeg",

        headers={

            "Cache-Control":
                "no-cache, no-store, must-revalidate",

            "Pragma":
                "no-cache",

            "Expires":
                "0"

        }

    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    print()

    print(
        "======================================"
    )

    print(
        "          CCTV SERVER"
    )

    print(
        "======================================"
    )

    print(
        f"TCP Client Port : {CLIENT_PORT}"
    )

    print(
        f"Web Port        : {WEB_PORT}"
    )

    print(
        f"Web             : http://SERVER-IP:{WEB_PORT}"
    )

    print(
        "Password        : 12345678"
    )

    print(
        "======================================"
    )

    print()


    threading.Thread(
        target=client_server,
        daemon=True
    ).start()


    threading.Thread(
        target=stream_monitor,
        daemon=True
    ).start()


    app.run(
        host=HOST,
        port=WEB_PORT,
        threaded=True,
        debug=False
    )
