import aiosqlite
import os
import logging
import secrets
import string
from datetime import datetime, timedelta
from config import settings

DB_PATH = settings.DB_PATH
logger = logging.getLogger(__name__)


async def init_db():
    """Initializes the SQLite database asynchronously."""

    logger.info(f"Attempting to initialize database at: {DB_PATH}")
    db_dir = os.path.dirname(DB_PATH)

    if db_dir and not os.path.exists(db_dir):
        logger.info(f"Creating directory: {db_dir}")
        os.makedirs(db_dir, exist_ok=True)
    elif not db_dir:
        logger.info("Database path is in the root directory. No directory to create.")

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            logger.info("Database connection successful. Creating tables...")
            
            # Основная таблица пользователей
            await db.execute("""
                CREATE TABLE IF NOT EXISTS linked_users (
                    telegram_id TEXT PRIMARY KEY,
                    jellyseerr_user_id TEXT,
                    jellyfin_user_id TEXT,
                    username TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    expires_at DATETIME,
                    guild_id TEXT,
                    role_name TEXT
                )
            """)
            
            # Таблица инвайт-кодов
            await db.execute("""
                CREATE TABLE IF NOT EXISTS invite_codes (
                    code TEXT PRIMARY KEY,
                    created_by TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    used_by TEXT,
                    used_at DATETIME,
                    expires_at DATETIME
                )
            """)
            
            # Таблица VIP статусов
            await db.execute("""
                CREATE TABLE IF NOT EXISTS vip_users (
                    telegram_id TEXT PRIMARY KEY,
                    vip_until DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (telegram_id) REFERENCES linked_users (telegram_id)
                )
            """)
            
            # Таблица пробных периодов
            await db.execute("""
                CREATE TABLE IF NOT EXISTS trial_users (
                    telegram_id TEXT PRIMARY KEY,
                    trial_start DATETIME DEFAULT CURRENT_TIMESTAMP,
                    trial_days INTEGER DEFAULT 7,
                    FOREIGN KEY (telegram_id) REFERENCES linked_users (telegram_id)
                )
            """)

            await db.commit()
            logger.info("Database tables created/verified successfully.")

    except Exception as e:
        logger.error(f"CRITICAL: Failed to initialize database: {e}")


async def delete_linked_user(telegram_id: str):
    """Deletes a linked user from the database by their ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM linked_users WHERE telegram_id=?", (str(telegram_id),)
        )
        await db.commit()


async def store_linked_user(
    telegram_id,
    jellyseerr_user_id,
    jellyfin_user_id,
    username=None,
    expires_at=None,
    guild_id=None,
    role_name=None,
):
    """Stores or updates a linked user in the database."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO linked_users (telegram_id, jellyseerr_user_id, jellyfin_user_id, username, expires_at, guild_id, role_name)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                jellyseerr_user_id=excluded.jellyseerr_user_id,
                jellyfin_user_id=excluded.jellyfin_user_id,
                username=excluded.username,
                expires_at=excluded.expires_at,
                guild_id=excluded.guild_id,
                role_name=excluded.role_name
        """,
            (
                str(telegram_id),
                jellyseerr_user_id,
                jellyfin_user_id,
                username,
                expires_at,
                guild_id,
                role_name,
            ),
        )
        await db.commit()


async def get_linked_user(telegram_id: str):
    """Retrieves a linked user's details by their ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT jellyseerr_user_id, jellyfin_user_id, username, expires_at
            FROM linked_users WHERE telegram_id=?
        """,
            (str(telegram_id),),
        ) as cursor:
            return await cursor.fetchone()


async def get_all_expiring_users():
    """Retrieves all IDs for users with an expiration date."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT telegram_id, jellyseerr_user_id, jellyfin_user_id, expires_at FROM linked_users WHERE expires_at IS NOT NULL"
        ) as cursor:
            return await cursor.fetchall()


async def get_all_linked_users():
    """Retrieves all users from the bot's database for /listusers."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT telegram_id, username, role_name, expires_at FROM linked_users ORDER BY created_at"
        ) as cursor:
            return await cursor.fetchall()


async def get_user_by_username(username: str):
    """Retrieves a user's IDs by their Jellyfin/Jellyseerr username."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT telegram_id, jellyseerr_user_id, jellyfin_user_id FROM linked_users WHERE username = ?",
            (username,),
        ) as cursor:
            return await cursor.fetchone()


# ---------- НОВЫЕ ФУНКЦИИ ----------

async def link_user(telegram_id: str, jellyseerr_user_id: str, username: str = None) -> bool:
    """Привязывает аккаунт Jellyseerr к Telegram ID."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO linked_users 
                (telegram_id, jellyseerr_user_id, jellyfin_user_id, username, created_at)
                VALUES (?, ?, NULL, ?, CURRENT_TIMESTAMP)
                """,
                (str(telegram_id), str(jellyseerr_user_id), username or "")
            )
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Ошибка при привязке пользователя: {e}")
        return False


async def check_trial(telegram_id: str) -> dict:
    """Проверяет наличие пробного периода у пользователя."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM trial_users 
            WHERE telegram_id = ? AND 
            date(trial_start, '+' || trial_days || ' days') > date('now')
            """,
            (str(telegram_id),)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "days_left": row["trial_days"] - (datetime.now() - datetime.fromisoformat(row["trial_start"])).days
                }
            return None


async def check_vip(telegram_id: str) -> dict:
    """Проверяет VIP статус пользователя."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM vip_users WHERE telegram_id = ? AND vip_until > datetime('now')",
            (str(telegram_id),)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "until": datetime.fromisoformat(row["vip_until"]).strftime("%d.%m.%Y")
                }
            return None


async def create_invite_code(telegram_id: str) -> str:
    """Создает инвайт-код для пользователя."""
    # Генерируем случайный код (8 символов)
    alphabet = string.ascii_uppercase + string.digits
    code = ''.join(secrets.choice(alphabet) for _ in range(8))
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT INTO invite_codes (code, created_by, expires_at)
                VALUES (?, ?, datetime('now', '+7 days'))
                """,
                (code, str(telegram_id))
            )
            await db.commit()
            return code
    except Exception as e:
        logger.error(f"Ошибка при создании инвайт-кода: {e}")
        return None


async def delete_user(telegram_id: str) -> bool:
    """Удаляет пользователя из всех таблиц."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Удаляем из всех таблиц
            await db.execute("DELETE FROM linked_users WHERE telegram_id = ?", (str(telegram_id),))
            await db.execute("DELETE FROM vip_users WHERE telegram_id = ?", (str(telegram_id),))
            await db.execute("DELETE FROM trial_users WHERE telegram_id = ?", (str(telegram_id),))
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Ошибка при удалении пользователя: {e}")
        return False


async def use_invite_code(code: str, telegram_id: str) -> bool:
    """Использует инвайт-код для регистрации."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Проверяем существование и срок действия кода
        async with db.execute(
            """
            SELECT * FROM invite_codes 
            WHERE code = ? AND used_by IS NULL AND expires_at > datetime('now')
            """,
            (code,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return False
        
        # Помечаем код как использованный
        await db.execute(
            "UPDATE invite_codes SET used_by = ?, used_at = datetime('now') WHERE code = ?",
            (str(telegram_id), code)
        )
        await db.commit()
        return True


async def activate_trial(telegram_id: str, days: int = 7) -> bool:
    """Активирует пробный период для пользователя."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO trial_users (telegram_id, trial_start, trial_days)
                VALUES (?, datetime('now'), ?)
                """,
                (str(telegram_id), days)
            )
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Ошибка при активации пробного периода: {e}")
        return False


async def set_vip(telegram_id: str, days: int = 30) -> bool:
    """Устанавливает VIP статус пользователю."""
    try:
        vip_until = datetime.now() + timedelta(days=days)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO vip_users (telegram_id, vip_until)
                VALUES (?, ?)
                """,
                (str(telegram_id), vip_until.isoformat())
            )
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Ошибка при установке VIP статуса: {e}")
        return False
