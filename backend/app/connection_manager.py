from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        # Each open socket mapped to its user's ID. One user can have several
        # sockets (for example, two browser tabs).
        self.active_connections: dict[WebSocket, int] = {}

    def connect(self, websocket: WebSocket, user_id: int) -> None:
        self.active_connections[websocket] = user_id

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.pop(websocket, None)

    async def broadcast(self, message: dict) -> None:
        await self._send(list(self.active_connections), message)

    async def send_to_users(self, user_ids: set[int], message: dict) -> None:
        connections = [
            connection
            for connection, user_id in list(self.active_connections.items())
            if user_id in user_ids
        ]
        await self._send(connections, message)

    async def _send(self, connections: list[WebSocket], message: dict) -> None:
        failed_connections: list[WebSocket] = []

        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception:
                failed_connections.append(connection)

        for connection in failed_connections:
            self.disconnect(connection)


manager = ConnectionManager()
