from __future__ import annotations

import argparse
import getpass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.repositories.postgres_repository import PostgresRepository
from backend.services.password_service import PasswordService

ADMIN_EMAIL = "aah5sgh@bosch.com"
AUTHORIZED_EMAILS = (
    "Lynette.LI@cn.bosch.com",
    "fixed-term.Yiheng.LU@cn.bosch.com",
    "fixed-term.Yaolong.ZHANG@cn.bosch.com",
    "Shawn.ZHANG2@cn.bosch.com",
    "Anna.Sun@cn.bosch.com",
    "Aaron.Wang@cn.bosch.com",
    "Yuanyuan.XU@cn.bosch.com",
    "Jialei.Xiao@cn.bosch.com",
    "Tong.Zhu3@cn.bosch.com",
    "Wei.Qu@cn.bosch.com",
    "Yajun.Rao@cn.bosch.com",
    "Weiting.Dai@cn.bosch.com",
    "Sicheng.Feng@cn.bosch.com",
    "Yiting.XU@cn.bosch.com",
    "Victor.LI@cn.bosch.com",
    "Richard.ZHU2@cn.bosch.com",
    "Yining.MA@cn.bosch.com",
    "Olivia.LI@cn.bosch.com",
    "Jian.XU2@cn.bosch.com",
    "Wenjie.Tong@cn.bosch.com",
    "Sha.LIANG@cn.bosch.com",
    "Jie.Chen3@cn.bosch.com",
    "Ting.GONG@cn.bosch.com"
)

def display_name(email: str) -> str:
    return email.split("@", 1)[0].replace("fixed-term.", "").replace(".", " ")

def main() -> None:
    parser = argparse.ArgumentParser(description="Provision the approved HRagent account whitelist.")
    parser.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args()
    password = sys.stdin.readline().rstrip("\n") if args.password_stdin else getpass.getpass("Initial password: ")
    password_service = PasswordService()
    password_service.hash_password(password)
    repo = PostgresRepository()
    approved = tuple(email.lower() for email in (ADMIN_EMAIL, *AUTHORIZED_EMAILS))

    with repo.connection() as conn:
        conn.execute("UPDATE auth_whitelist SET enabled = FALSE WHERE lower(email::text) <> ALL(%s)", (list(approved),))
        conn.execute("UPDATE locust_test_credentials SET enabled = FALSE")
        for raw_email in (ADMIN_EMAIL, *AUTHORIZED_EMAILS):
            email = raw_email.lower()
            role = "admin" if email == ADMIN_EMAIL else "user"
            password_hash = password_service.hash_password(password)
            conn.execute(
                """
                INSERT INTO auth_whitelist (email, enabled, note)
                VALUES (%s, TRUE, 'approved fixed account')
                ON CONFLICT (email) DO UPDATE SET enabled = TRUE, note = EXCLUDED.note
                """,
                (email,),
            )
            conn.execute(
                """
                INSERT INTO app_users (email, display_name, password_hash, auth_provider, role, is_active, is_email_verified)
                VALUES (%s, %s, %s, 'local', %s, TRUE, TRUE)
                ON CONFLICT (email) DO UPDATE SET
                    display_name = EXCLUDED.display_name, password_hash = EXCLUDED.password_hash,
                    role = EXCLUDED.role, is_active = TRUE, is_email_verified = TRUE, updated_at = NOW()
                """,
                (email, display_name(email), password_hash, role),
            )
            if role == "user":
                conn.execute(
                    """
                    INSERT INTO locust_test_credentials (email, password_nonce, enabled)
                    VALUES (%s, 'approved-fixed-account', TRUE)
                    ON CONFLICT (email) DO UPDATE SET enabled = TRUE, updated_at = NOW()
                    """,
                    (email,),
                )
    print({"ok": True, "authorized_accounts": len(approved), "load_test_accounts": len(AUTHORIZED_EMAILS)})

if __name__ == "__main__":
    main()
