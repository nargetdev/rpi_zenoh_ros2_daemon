from __future__ import annotations

import json
import logging
import threading
import time
import uuid

import zenoh
from zenoh_ros2_sdk import ROS2ServiceServer

from .capture_backends import build_backend
from .heartbeat import HeartbeatBroadcaster, PgwaamOnlineBroadcaster
from .models import PiRuntimeSettings


LOGGER = logging.getLogger("zenoh_dslr_pi_runtime")
SERVICE_TYPE = "std_srvs/srv/SetBool"
REQUEST_DEFINITION = "bool data"
RESPONSE_DEFINITION = "bool success\nstring message"


class PiDslrRuntime:
    def __init__(self, settings: PiRuntimeSettings) -> None:
        self._settings = settings
        self._backend = build_backend(settings)
        self._stop_event = threading.Event()
        self._capture_lock = threading.Lock()
        self._capture_count = 0

    def run(self) -> None:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        config = (
            zenoh.Config.from_file(self._settings.zenoh_config_path)
            if self._settings.zenoh_config_path
            else zenoh.Config()
        )
        with zenoh.open(config) as session:
            server_holder: dict[str, ROS2ServiceServer] = {}
            service_server = ROS2ServiceServer(
                service_name=self._settings.capture_service_name,
                srv_type=SERVICE_TYPE,
                request_definition=REQUEST_DEFINITION,
                response_definition=RESPONSE_DEFINITION,
                callback=self._handle_capture(session, server_holder),
                router_ip=self._settings.router_ip,
                router_port=self._settings.router_port,
            )
            server_holder["server"] = service_server
            LOGGER.info("serving ROS 2 capture service on %s", self._settings.capture_service_name)
            heartbeat = HeartbeatBroadcaster(session, self._settings, capture_count=lambda: self._capture_count)
            heartbeat.start()
            pgwaam = PgwaamOnlineBroadcaster(self._settings)
            pgwaam.start()
            try:
                while not self._stop_event.is_set():
                    time.sleep(0.25)
            finally:
                pgwaam.stop()
                heartbeat.stop()
                service_server.close()

    def stop(self) -> None:
        self._stop_event.set()

    def _handle_capture(self, session: zenoh.Session, server_holder: dict[str, ROS2ServiceServer]):
        def do_capture(request_id: str) -> None:
            try:
                LOGGER.info("capture job %s started for %s", request_id, self._settings.camera_id)
                frame = self._backend.capture()
                if self._settings.publish_delay_ms > 0:
                    time.sleep(self._settings.publish_delay_ms / 1000.0)
                session.put(
                    frame.image_key,
                    frame.payload,
                    encoding=frame.encoding,
                    attachment=json.dumps(frame.metadata),
                )
                self._capture_count += 1
                LOGGER.info(
                    "capture job %s published capture %s to %s",
                    request_id,
                    frame.capture_id,
                    frame.image_key,
                )
            except Exception:
                LOGGER.exception("capture job %s failed", request_id)
            finally:
                self._capture_lock.release()

        def on_request(_request):
            response_type = server_holder["server"].response_msg_class
            if not self._capture_lock.acquire(blocking=False):
                return response_type(
                    success=False,
                    message=json.dumps(
                        {
                            "camera_id": self._settings.camera_id,
                            "camera_model": self._settings.camera_model,
                            "message": "capture already in progress",
                        }
                    ),
                )

            request_id = uuid.uuid4().hex
            LOGGER.info("capture request %s accepted for %s", request_id, self._settings.camera_id)
            threading.Thread(
                target=do_capture,
                args=(request_id,),
                name=f"capture-{self._settings.camera_id}",
                daemon=True,
            ).start()
            return response_type(
                success=True,
                message=json.dumps(
                    {
                        "request_id": request_id,
                        "camera_id": self._settings.camera_id,
                        "camera_model": self._settings.camera_model,
                        "frame_key_prefix": self._settings.frame_key_prefix,
                        "message": "capture accepted",
                    }
                ),
            )

        return on_request
