from typing import Dict, List
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        # train_id -> list of WebSockets
        self.train_connections: Dict[int, List[WebSocket]] = {}
        # control room websockets
        self.control_connections: List[WebSocket] = []

    async def connect_train(self, websocket: WebSocket, train_id: int):
        await websocket.accept()
        if train_id not in self.train_connections:
            self.train_connections[train_id] = []
        self.train_connections[train_id].append(websocket)

    def disconnect_train(self, websocket: WebSocket, train_id: int):
        if train_id in self.train_connections and websocket in self.train_connections[train_id]:
            self.train_connections[train_id].remove(websocket)

    async def connect_control(self, websocket: WebSocket):
        await websocket.accept()
        self.control_connections.append(websocket)

    def disconnect_control(self, websocket: WebSocket):
        if websocket in self.control_connections:
            self.control_connections.remove(websocket)

    async def broadcast_train_update(self, train_id: int, message: dict):
        if train_id in self.train_connections:
            dead_sockets = []
            for ws in self.train_connections[train_id]:
                try:
                    await ws.send_json(message)
                except Exception:
                    dead_sockets.append(ws)
            for ws in dead_sockets:
                self.train_connections[train_id].remove(ws)

    async def broadcast_control_room(self, message: dict):
        dead_sockets = []
        for ws in self.control_connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead_sockets.append(ws)
        for ws in dead_sockets:
            self.control_connections.remove(ws)

manager = ConnectionManager()
