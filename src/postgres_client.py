import os
from sqlalchemy import create_engine, MetaData, Table, select, update
from sqlalchemy.orm import sessionmaker
import logging
import time

logger = logging.getLogger(__name__)

class PostgresClient:
    def __init__(self, user, password, host, port, db, table):
        self.db_url = f'postgresql://{user}:{password}@{host}:{port}/{db}'
        self.table_name = table
        self.engine = None
        self.metadata = None
        self.table = None
        self.Session = None

    def connect(self, logger=None, retry_interval=5):
        while True:
            try:
                # Always dispose previous engine before connecting to avoid resource leaks
                try:
                    if self.engine is not None:
                        self.engine.dispose()
                        self.engine = None
                except Exception:
                    pass  # Ignore errors if not connected

                self.engine = create_engine(self.db_url)
                self.metadata = MetaData()
                self.table = Table(self.table_name, self.metadata, autoload_with=self.engine)
                self.Session = sessionmaker(bind=self.engine)
                if logger:
                    logger.info(f"PostgreSQL Connected to {self.db_url}")
                break
            except Exception as e:
                if logger:
                    logger.error(f"DB connection error: {e}. Retrying in {retry_interval} seconds...")
                time.sleep(retry_interval)

    def get_record(self, record_id):
        if self.engine is None:
            raise RuntimeError("PostgresClient not connected. Call connect() first")
        with self.engine.connect() as conn:
            stmt = select(self.table).where(self.table.c.id == record_id)
            result = conn.execute(stmt).fetchone()
            return dict(result._mapping) if result else {}

    def upsert(self, record_id, payload):
        if self.engine is None:
            raise RuntimeError("PostgresClient not connected. Call connect() first")
        with self.engine.connect() as conn:
            stmt = update(self.table).where(self.table.c.id == record_id).values(**payload)
            conn.execute(stmt)
            conn.commit()
            logger.info(f"Upserted record {record_id} in {self.table_name}")

    def disconnect(self):
        if self.engine is not None:
            self.engine.dispose()
            logger.info("DB disconnected")
