
# bot/services/user_state.py
from enum import Enum, auto

class UserState(Enum):
    NONE = auto()
    REQUEST_SEARCH = auto()
    LINK_CREDENTIALS = auto()
    ADMIN_INVITE = auto()      # ← Новый
    ADMIN_TRIAL = auto()       # ← Новый
    ADMIN_VIP = auto()         # ← Новый

class UserStateManager:
    def __init__(self):
        self.states = {}
        self.pending_data = {}  # Для хранения reply_to_message

    def set(self, user_id: int, state: UserState, data=None):
        self.states[user_id] = state
        if data is not None:
            self.pending_data[user_id] = data

    def get(self, user_id: int) -> UserState:
        return self.states.get(user_id, UserState.NONE)

    def get_data(self, user_id: int):
        return self.pending_data.get(user_id)

    def clear(self, user_id: int):
        self.states.pop(user_id, None)
        self.pending_data.pop(user_id, None)

user_states = UserStateManager()
