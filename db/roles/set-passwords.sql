-- Run by services/migrator/entrypoint.sh after every `dbmate up`.
-- Values come from .env via psql variables; they are never stored in migrations.
ALTER ROLE tipg_ro    PASSWORD :'tipg_pw';
ALTER ROLE app_rw     PASSWORD :'app_pw';
ALTER ROLE loader     PASSWORD :'loader_pw';
ALTER ROLE worker_rw  PASSWORD :'worker_pw';
ALTER ROLE analyst_ro PASSWORD :'analyst_pw';
