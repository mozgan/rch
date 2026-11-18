"""PostGIS backend and isolated PostgreSQL lifecycle for exact point-window benchmarks."""
from __future__ import annotations
import contextlib
import os
import pwd
import shutil
import subprocess
import uuid
from pathlib import Path
import psycopg
from psycopg import sql

LAYOUTS = ('input', 'hilbert', 'rch')
BACKENDS = tuple(f'{layout}_{mode}' for layout in LAYOUTS for mode in ('seq', 'ndgist'))
SETTINGS = {'max_parallel_workers_per_gather': '0', 'jit': 'off', 'work_mem': '64MB',
            'plan_cache_mode': 'force_custom_plan', 'statement_timeout': '300000'}


def pg_binary(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    candidates = sorted(Path('/usr/lib/postgresql').glob(f'*/bin/{name}'),
                        key=lambda p: int(p.parents[1].name), reverse=True)
    if not candidates:
        raise RuntimeError(f'{name} missing; install PostgreSQL server packages from docs/requirements.md')
    return str(candidates[0])


@contextlib.contextmanager
def managed_server(log_path: Path):
    """Private socket-only cluster; never change a system service/role/database."""
    root = os.geteuid() == 0
    parent = Path('/var/lib/postgresql') if root else Path.home() / 'tmp/rch_dbms'
    parent.mkdir(parents=True, exist_ok=True)
    runtime = parent / ('rch_' + uuid.uuid4().hex[:12])
    runtime.mkdir(mode=0o700)
    prefix = []
    if root:
        owner = pwd.getpwnam('postgres')
        os.chown(runtime, owner.pw_uid, owner.pw_gid)
        prefix = ['runuser', '-u', 'postgres', '--']
    socket = runtime / 'socket'
    socket.mkdir(mode=0o700)
    if root:
        os.chown(socket, owner.pw_uid, owner.pw_gid)
    if len(str(socket / '.s.PGSQL.5432')) >= 100:
        shutil.rmtree(runtime)
        raise RuntimeError('PostgreSQL Unix socket path too long')
    data = runtime / 'data'
    server_log = runtime / 'server.log'
    started = False
    stopped = False
    try:
        subprocess.run(prefix + [pg_binary('initdb'), '-D', str(data), '-U', 'rch_bench',
                       '--auth-local=trust', '--auth-host=reject', '--encoding=UTF8', '--no-locale'],
                       check=True, capture_output=True, text=True)
        # Configuration is private to this newly created cluster. TCP is disabled.
        with (data / 'postgresql.conf').open('a') as handle:
            socket_config = str(socket).replace("'", "''")
            handle.write(f"\nlisten_addresses = ''\nunix_socket_directories = '{socket_config}'\n"
                         "shared_buffers = '256MB'\nmax_connections = 10\nfsync = on\n")
        subprocess.run(prefix + [pg_binary('pg_ctl'), '-D', str(data), '-l', str(server_log), '-w', 'start'],
                       check=True, capture_output=True, text=True)
        started = True
        admin = dict(host=str(socket), user='rch_bench', dbname='postgres', port=5432)
        with psycopg.connect(**admin, autocommit=True) as connection:
            connection.execute('CREATE DATABASE rch_bench')
        yield dict(host=str(socket), user='rch_bench', dbname='rch_bench', port=5432)
    finally:
        started = started or (data / 'postmaster.pid').exists()
        if started:
            status = subprocess.run(prefix + [pg_binary('pg_ctl'), '-D', str(data), '-m', 'fast', '-w', 'stop'],
                                    capture_output=True, text=True)
            stopped = status.returncode == 0
        if server_log.exists():
            log_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(server_log, log_path)
        if not started or stopped:
            shutil.rmtree(runtime)
        else:
            raise RuntimeError(f'could not stop private PostgreSQL; runtime retained: {runtime}')


def connect(connection):
    kwargs = connection if isinstance(connection, dict) else {'conninfo': connection}
    conn = psycopg.connect(**kwargs, autocommit=True, connect_timeout=10, prepare_threshold=None,
                           application_name='rch_dbms_benchmark')
    for name, value in SETTINGS.items():
        conn.execute('SELECT set_config(%s,%s,false)', (name, value))
    return conn


def server_info(conn) -> dict:
    version = conn.execute('SELECT version(), postgis_full_version(), current_setting(\'server_version_num\')').fetchone()
    names = ('shared_buffers', 'work_mem', 'effective_cache_size', 'random_page_cost', 'seq_page_cost',
             'max_parallel_workers_per_gather', 'jit', 'plan_cache_mode', 'fsync', 'block_size')
    return {'postgresql': version[0], 'postgis': version[1], 'version_num': version[2],
            'settings': {name: conn.execute('SELECT current_setting(%s)', (name,)).fetchone()[0] for name in names}}


def table_name(schema: str, layout: str):
    if layout not in LAYOUTS:
        raise ValueError('unknown layout')
    return sql.Identifier(schema, layout)


def create_table(conn, schema: str, layout: str):
    conn.execute(sql.SQL('CREATE TABLE {} (point_id bigint NOT NULL, x double precision NOT NULL, '
                        'y double precision NOT NULL,z double precision NOT NULL, '
                        'geom geometry(PointZ,0) GENERATED ALWAYS AS (ST_MakePoint(x,y,z)) STORED)').format(table_name(schema, layout)))


def query_statement(schema: str, backend: str):
    if backend not in BACKENDS:
        raise ValueError('unknown backend')
    layout, mode = backend.rsplit('_', 1)
    exact = sql.SQL('x >= %s AND y >= %s AND z >= %s AND x <= %s AND y <= %s AND z <= %s')
    if mode == 'ndgist':
        # A line between opposite corners has exactly the required 3D bounding box.
        exact = sql.SQL('geom &&& ST_MakeLine(ST_MakePoint(%s,%s,%s),ST_MakePoint(%s,%s,%s)) AND ') + exact
    return sql.SQL('SELECT point_id FROM {} WHERE {} ORDER BY point_id').format(table_name(schema, layout), exact)


def parameters(bounds, backend: str):
    return tuple(bounds) * (2 if backend.endswith('_ndgist') else 1)


def configure_scan(conn, backend: str):
    seq = backend.endswith('_seq')
    conn.execute('SELECT set_config(\'enable_indexscan\', %s, false)', ('off' if seq else 'on',))
    conn.execute('SELECT set_config(\'enable_bitmapscan\', %s, false)', ('off' if seq else 'on',))
    conn.execute('SELECT set_config(\'enable_indexonlyscan\', %s, false)', ('off' if seq else 'on',))
    conn.execute('SET enable_seqscan = on')  # Indexed arms retain the optimizer's choice.


def nodes(plan):
    yield plan
    for child in plan.get('Plans', []):
        yield from nodes(child)
