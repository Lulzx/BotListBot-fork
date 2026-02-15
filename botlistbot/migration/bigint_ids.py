"""
Migration: IntegerField -> BigIntegerField for Telegram IDs

Telegram user/chat IDs have exceeded the 32-bit signed integer limit (2,147,483,647).
Newer accounts have IDs that overflow IntegerField. This migration widens all
Telegram ID columns to BIGINT (64-bit).

Usage:
    python -m botlistbot.migration.bigint_ids
"""
import sys
from pathlib import Path

botlistbot_path = str((Path(__file__).parent.parent.parent).absolute())
if botlistbot_path not in sys.path:
    sys.path.insert(0, botlistbot_path)

from peewee import BigIntegerField
from playhouse.migrate import PostgresqlMigrator, migrate

from botlistbot import appglobals

migrator = PostgresqlMigrator(appglobals.db)

MIGRATIONS = [
    # (table_name, column_name)
    ("user", "chat_id"),
    ("group", "chat_id"),
    ("bot", "chat_id"),
    ("message", "chat_id"),
]


def run():
    print("Migrating IntegerField -> BigIntegerField for Telegram ID columns...")
    for table, column in MIGRATIONS:
        print(f"  ALTER TABLE {table}: {column} -> BIGINT ... ", end="")
        try:
            migrate(
                migrator.alter_column_type(table, column, BigIntegerField(null=True)),
            )
            print("OK")
        except Exception as e:
            print(f"SKIPPED ({e})")
    print("Done.")


if __name__ == "__main__":
    run()
